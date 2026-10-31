"""Offline, synthetic SQL snapshot audit; never calls an API or sends alerts."""
import copy

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, Record
from app.forecast_alert_atomic_snapshot import audit_persisted_forecast_alerts
from app.forecast_alert_outbox import ForecastAlertOutbox
from app.forecast_event_store import ForecastEventStore

SESSION = "session1"
FORECAST = "forecast1"
FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
        "sourceId": "offline", "priceSide": "bid", "seconds": 60}


def fixture_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    journal = {"version": 1, "identity": copy.deepcopy(FEED), "maxLagSeconds": 120,
               "events": [
                   {"seq": 1, "receivedAt": 120, "kind": "CANDLE", "start": 60,
                    "close": 100.0},
                   {"seq": 2, "receivedAt": 120, "kind": "FORECAST", "id": FORECAST,
                    "modelVersion": "baseline", "horizon": 1, "probability": 0.6,
                    "baseStart": 60}]}
    alert = {"version": 1, "identity": copy.deepcopy(FEED),
             "forecastId": FORECAST, "modelVersion": "baseline", "horizon": 1,
             "baseStart": 60, "issueSeq": 2, "issuedAt": 120, "expiresAt": 180,
             "status": "QUEUED", "claimId": None, "claimedAt": None, "ackAt": None}
    with factory.begin() as db:
        db.add(Record(key=ForecastEventStore._key(SESSION),
                      value=ForecastEventStore._pack(journal)))
        db.add(Record(key=ForecastAlertOutbox._key(SESSION, FORECAST),
                      value=ForecastAlertOutbox._pack(alert)))
    return engine, factory


def audit(factory):
    return audit_persisted_forecast_alerts([SESSION], [(SESSION, FORECAST)],
                                            as_of=150, session_factory=factory)


def test_one_statement_read_only_and_no_authority():
    engine, factory = fixture_db()
    sql = []
    def capture(_conn, _cursor, statement, _params, _context, _executemany):
        sql.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    result = audit(factory)
    assert len(sql) == 1 and sql[0].lstrip().upper().startswith("SELECT")
    assert result["snapshotEvidence"] == "ONE_SQL_STATEMENT_DECLARED_INVENTORY"
    assert result["persistedAlertCount"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"  # 30s to expiry
    assert result["independentlyComplete"] is False
    assert result["transactionallyStableAfterRead"] is False
    assert all(result[k] is False for k in
               ("maySendNotification", "mayExecutePaperOrder", "mayExecuteLiveOrder"))
    with factory() as db:
        assert len(db.execute(select(Record.key)).all()) == 2
    engine.dispose()


def test_undeclared_persisted_alert_fails_closed():
    engine, factory = fixture_db()
    with factory.begin() as db:
        db.add(Record(key=ForecastAlertOutbox._key(SESSION, "hidden"), value="{}"))
    with pytest.raises(ValueError, match="Undeclared persisted"):
        audit(factory)
    engine.dispose()


def test_undeclared_journal_without_alert_fails_closed():
    engine, factory = fixture_db()
    # A valid-looking extra journal can be omitted even when it has no alert.
    # The audit must not accept a partial declared session inventory.
    with factory.begin() as db:
        db.add(Record(key=ForecastEventStore._key("hidden_session"), value="{}"))
    with pytest.raises(ValueError, match="Undeclared persisted forecast journal"):
        audit(factory)
    engine.dispose()


def test_empty_inventory_does_not_hide_orphan_journal():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory.begin() as db:
        db.add(Record(key=ForecastEventStore._key("orphan_session"), value="{}"))
    with pytest.raises(ValueError, match="Undeclared persisted forecast journal"):
        audit_persisted_forecast_alerts([], [], as_of=150,
                                        session_factory=factory)
    engine.dispose()


def test_missing_journal_and_missing_alert_fail_closed():
    for key in (ForecastEventStore._key(SESSION),
                ForecastAlertOutbox._key(SESSION, FORECAST)):
        engine, factory = fixture_db()
        with factory.begin() as db:
            db.delete(db.get(Record, key))
        with pytest.raises(ValueError, match="Missing persisted"):
            audit(factory)
        engine.dispose()


def test_corrupt_alert_fails_closed():
    engine, factory = fixture_db()
    with factory.begin() as db:
        db.get(Record, ForecastAlertOutbox._key(SESSION, FORECAST)).value = "{}"
    with pytest.raises(ValueError, match="Outbox integrity failure"):
        audit(factory)
    engine.dispose()


def test_cross_store_identity_mismatch_fails_closed():
    engine, factory = fixture_db()
    key = ForecastAlertOutbox._key(SESSION, FORECAST)
    with factory.begin() as db:
        row = db.get(Record, key)
        state = ForecastAlertOutbox._unpack(row.value, 150)
        state["modelVersion"] = "wrong"
        row.value = ForecastAlertOutbox._pack(state)
    with pytest.raises(ValueError, match="identity mismatch"):
        audit(factory)
    engine.dispose()


@pytest.mark.parametrize("session_ids,expected", [
    ([SESSION, SESSION], [(SESSION, FORECAST)]),
    ([SESSION], [(SESSION, FORECAST), (SESSION, FORECAST)]),
    ([SESSION], [("other", FORECAST)]),
    ([SESSION], []),
    ([SESSION], [(SESSION, "bad:id")]),
    ([], [(SESSION, FORECAST)]),
])
def test_invalid_inventory_rejected_before_read(session_ids, expected):
    engine, factory = fixture_db()
    with pytest.raises(ValueError):
        audit_persisted_forecast_alerts(session_ids, expected, as_of=150,
                                        session_factory=factory)
    engine.dispose()


def test_empty_database_has_no_false_success():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    result = audit_persisted_forecast_alerts([], [], as_of=150,
                                             session_factory=sessionmaker(engine))
    assert result["status"] == "NO_DECLARED_ALERTS"
    assert result["sourceAuthenticated"] is False
    engine.dispose()


def test_empty_declared_inventory_does_not_hide_existing_alert():
    engine, factory = fixture_db()
    with pytest.raises(ValueError, match="Undeclared"):
        audit_persisted_forecast_alerts([], [], as_of=150, session_factory=factory)
    engine.dispose()


def test_excess_persisted_rows_fail_closed():
    engine, factory = fixture_db()
    with factory.begin() as db:
        for i in range(2000):
            db.add(Record(key=f"forecast-alert:{i:064x}", value="{}"))
    with pytest.raises(ValueError, match="row limit"):
        audit(factory)
    engine.dispose()


@pytest.mark.parametrize("bad", [True, -1, 1.5, 2**53])
def test_invalid_clock_rejected(bad):
    engine, factory = fixture_db()
    with pytest.raises(ValueError, match="audit time"):
        audit_persisted_forecast_alerts([SESSION], [(SESSION, FORECAST)],
                                        as_of=bad, session_factory=factory)
    engine.dispose()
