"""Single-statement, read-only forecast journal/outbox snapshot reconciliation.

This disconnected audit observes one database statement snapshot, NOT an
authenticated market feed or a complete independently attested inventory.
Never use its result to authorize a notification or any trade.
"""

from sqlalchemy import or_, select

from .db import Record, Session
from .forecast_alert_outbox import ForecastAlertOutbox
from .forecast_alert_journal_reconciliation import reconcile_forecast_alert_journals
from .forecast_event_store import ForecastEventStore, _epoch

_MAX_KEYS = 1000
_MAX_ROWS = 2 * _MAX_KEYS
_MAX_TOTAL_BYTES = 16_000_000


def audit_persisted_forecast_alerts(session_ids, expected_keys, *, as_of,
                                    session_factory=Session):
    """Reconcile one bounded SQL statement snapshot of persisted forecast state.

    The caller supplies the registered session/alert inventory. Every persisted
    ``forecast-alert:`` row in the same database is enumerated in the *same*
    SELECT as requested journals. Unregistered alerts, missing rows, excessive
    size, corruption, and inconsistent journal/alert contents fail closed.
    No claim, retry, send, or order is performed. A concurrent later write can
    change the database after the statement; this is NOT a delivery guarantee.
    """
    if not _epoch(as_of):
        raise ValueError("Invalid forecast snapshot audit time")
    if (type(session_ids) is not list or type(expected_keys) is not list or
            len(session_ids) > _MAX_KEYS or len(expected_keys) > _MAX_KEYS):
        raise ValueError("Invalid bounded forecast snapshot inventory")
    if any(type(s) is not str for s in session_ids) or len(set(session_ids)) != len(session_ids):
        raise ValueError("Duplicate or invalid forecast snapshot session")
    journal_keys = {}
    for session_id in session_ids:
        key = ForecastEventStore._key(session_id)
        journal_keys[key] = session_id
    alert_keys = {}
    for item in expected_keys:
        if type(item) not in (list, tuple) or len(item) != 2:
            raise ValueError("Invalid forecast snapshot alert identity")
        session_id, forecast_id = item
        if type(session_id) is not str or session_id not in session_ids:
            raise ValueError("Alert outside declared forecast sessions")
        key = ForecastAlertOutbox._key(session_id, forecast_id)
        if key in alert_keys:
            raise ValueError("Duplicate forecast snapshot alert")
        alert_keys[key] = (session_id, forecast_id)
    if set(session_ids) != {s for s, _ in alert_keys.values()}:
        raise ValueError("Incomplete declared forecast snapshot sessions")

    # One SELECT matters: separate journal and outbox reads under the default
    # READ COMMITTED isolation could observe different committed revisions.
    # The bounded scan also catches alert rows omitted from the declared list.
    predicate = Record.key.like("forecast-alert:%")
    if journal_keys:
        predicate = or_(predicate, Record.key.in_(journal_keys))
    with session_factory() as db:
        rows = db.execute(select(Record.key, Record.value).where(predicate)
                          .order_by(Record.key).limit(_MAX_ROWS + 1)).all()
    if len(rows) > _MAX_ROWS:
        raise ValueError("Forecast snapshot row limit exceeded")
    raw = {}
    total_bytes = 0
    for key, value in rows:
        if type(key) is not str or type(value) is not str:
            raise ValueError("Malformed persisted forecast snapshot")
        total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ValueError("Forecast snapshot byte limit exceeded")
        if key not in journal_keys and key not in alert_keys:
            raise ValueError("Undeclared persisted forecast alert")
        if key in raw:
            raise ValueError("Duplicate persisted forecast row")
        raw[key] = value
    if set(raw) != set(journal_keys) | set(alert_keys):
        raise ValueError("Missing persisted forecast snapshot row")

    journals = []
    for key, session_id in journal_keys.items():
        payload, forecasts = ForecastEventStore._unpack(raw[key], as_of)
        journals.append({"sessionId": session_id, "snapshot": {
            "sequence": len(payload["events"]), "identity": payload["identity"],
            "maxLagSeconds": payload["maxLagSeconds"], "events": payload["events"],
            "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}})
    alerts = []
    for key, (session_id, _forecast_id) in alert_keys.items():
        alerts.append({"sessionId": session_id,
                       "state": ForecastAlertOutbox._unpack(raw[key], as_of)})
    result = reconcile_forecast_alert_journals(journals, alerts, expected_keys,
                                                as_of=as_of)
    # Explicitly distinguish a single SQL statement from a trustworthy,
    # independently authenticated expected population or stable future state.
    return {**result, "snapshotEvidence": "ONE_SQL_STATEMENT_DECLARED_INVENTORY",
            "persistedAlertCount": len(alert_keys),
            "independentlyComplete": False,
            "transactionallyStableAfterRead": False,
            "maySendNotification": False, "mayExecutePaperOrder": False,
            "mayExecuteLiveOrder": False}
