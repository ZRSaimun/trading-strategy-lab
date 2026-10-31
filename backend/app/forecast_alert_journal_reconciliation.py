"""Read-only reconciliation of declared alert rows against replayed forecast journals.

Only use snapshots from ForecastEventStore.load and raw states decoded by
ForecastAlertOutbox._unpack. Neither store authenticates market observations,
provider delivery, or the completeness of a caller-declared population.
"""
from collections import Counter

from .forecast_alert_health_audit import audit_forecast_alert_health
from .forecast_event_store import _replay

_MAX_SESSIONS = 1000
_JOURNAL_KEYS = {"sequence", "identity", "maxLagSeconds", "events", "forecasts", "evidence"}


def reconcile_forecast_alert_journals(journals, records, expected_keys, *, as_of):
    """Fail closed on inconsistent forecast/alert identities; never authorize sends.

    journals: [{"sessionId": str, "snapshot": ForecastEventStore.load result}]
    records: [{"sessionId": str, "state": ForecastAlertOutbox._unpack result}]
    expected_keys: independent *caller-declared* [(sessionId, forecastId), ...].
    Snapshots/records must be taken from a consistent database snapshot by the
    eventual caller; this pure function does not provide transaction isolation.
    """
    health = audit_forecast_alert_health(records, expected_keys, as_of=as_of)
    if type(journals) is not list or len(journals) > _MAX_SESSIONS:
        raise ValueError("Invalid bounded forecast journal population")
    expected_sessions = {session for session, _forecast in expected_keys}
    snapshots = {}
    event_maps = {}
    forecast_maps = {}
    for item in journals:
        if type(item) is not dict or set(item) != {"sessionId", "snapshot"}:
            raise ValueError("Malformed forecast journal inventory")
        session, snapshot = item["sessionId"], item["snapshot"]
        if type(session) is not str or session not in expected_sessions or session in snapshots:
            raise ValueError("Unexpected or duplicate forecast journal session")
        if type(snapshot) is not dict or set(snapshot) != _JOURNAL_KEYS or \
                snapshot["evidence"] != "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL" or \
                type(snapshot["events"]) is not list or \
                type(snapshot["sequence"]) is not int or \
                snapshot["sequence"] != len(snapshot["events"]):
            raise ValueError("Invalid forecast journal snapshot")
        # Recompute outcomes from immutable issuance/candle events. A caller's
        # supplied derived status or settlement cannot silently override replay.
        try:
            computed = _replay({"version": 1, "identity": snapshot["identity"],
                                "maxLagSeconds": snapshot["maxLagSeconds"],
                                "events": snapshot["events"]}, as_of)
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise ValueError("Invalid forecast journal event history") from exc
        if type(snapshot["forecasts"]) is not list or snapshot["forecasts"] != computed:
            raise ValueError("Forecast outcomes disagree with journal replay")
        event_maps[session] = {event["id"]: event for event in snapshot["events"]
                               if event["kind"] == "FORECAST"}
        forecast_maps[session] = {row["id"]: row for row in computed}
        snapshots[session] = snapshot
    if set(snapshots) != expected_sessions:
        raise ValueError("Incomplete declared forecast journal population")

    counts = Counter()
    review_keys = []
    for record in records:
        session, state = record["sessionId"], record["state"]
        fid = state["forecastId"]
        event = event_maps[session].get(fid)
        forecast = forecast_maps[session].get(fid)
        if event is None or forecast is None:
            raise ValueError("Orphaned forecast alert")
        identity = snapshots[session]["identity"]
        if (state["identity"] != identity or
                state["issueSeq"] != event["seq"] or
                state["modelVersion"] != event["modelVersion"] or
                state["horizon"] != event["horizon"] or
                state["baseStart"] != event["baseStart"] or
                state["issuedAt"] != event["receivedAt"]):
            raise ValueError("Forecast alert journal identity mismatch")
        # The actual outbox caps expiry by both configured age (<=3600s)
        # and the target completed candle. This also catches forged expiry.
        target_close = forecast["targetStart"] + identity["seconds"]
        if not state["issuedAt"] < state["expiresAt"] <= min(
                state["issuedAt"] + 3600, target_close):
            raise ValueError("Forecast alert expiry exceeds issuance bounds")
        counts[forecast["status"]] += 1
        if forecast["status"] != "PENDING" and state["status"] != "CANCELLED":
            counts["RESOLVED_NONCANCELLED"] += 1
            review_keys.append([session, fid])
    review = (health["status"] == "OPERATOR_REVIEW_REQUIRED" or
              counts["RESOLVED_NONCANCELLED"] > 0)
    return {
        "status": "NO_DECLARED_ALERTS" if not expected_keys else
                  "OPERATOR_REVIEW_REQUIRED" if review else "DECLARED_ONLY",
        "populationEvidence": "DECLARED_ONLY_NOT_INDEPENDENTLY_VERIFIED",
        "declaredCount": len(expected_keys),
        "forecastCounts": {name: counts[name] for name in
                           ("PENDING", "SETTLED", "VOID_GAP", "RESOLVED_NONCANCELLED")},
        "resolvedNoncancelledKeys": sorted(review_keys),
        "alertHealth": health,
        "sourceAuthenticated": False,
        "providerDeliveryVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
