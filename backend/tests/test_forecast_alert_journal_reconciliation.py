"""Synthetic offline reconciliation tests: no feed, HTTP, broker or order path."""
import copy

import pytest

from app.forecast_event_store import _replay
from app.forecast_alert_journal_reconciliation import reconcile_forecast_alert_journals as audit


FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
        "sourceId": "offline", "priceSide": "bid", "seconds": 60}
SESSION = "session1"
FORECAST = "forecast1"


def make_case(*, as_of=150, state_status="QUEUED", candle=None):
    events = [
        {"seq": 1, "receivedAt": 120, "kind": "CANDLE", "start": 60, "close": 100.0},
        {"seq": 2, "receivedAt": 120, "kind": "FORECAST", "id": FORECAST,
         "modelVersion": "baseline", "horizon": 1, "probability": 0.6,
         "baseStart": 60},
    ]
    if candle is not None:
        events.append({"seq": 3, "receivedAt": as_of, "kind": "CANDLE",
                       "start": candle, "close": 101.0})
    snapshot = {"sequence": len(events), "identity": copy.deepcopy(FEED),
                "maxLagSeconds": 120, "events": events,
                "forecasts": _replay({"version": 1, "identity": FEED,
                                      "maxLagSeconds": 120, "events": events}, as_of),
                "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}
    state = {"version": 1, "identity": copy.deepcopy(FEED),
             "forecastId": FORECAST, "modelVersion": "baseline", "horizon": 1,
             "baseStart": 60, "issueSeq": 2, "issuedAt": 120, "expiresAt": 180,
             "status": state_status, "claimId": None, "claimedAt": None, "ackAt": None}
    if state_status in ("IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED"):
        state.update(claimId="a" * 32, claimedAt=130)
    if state_status == "ACK_RECORDED_UNVERIFIED":
        state["ackAt"] = 140
    return ([{"sessionId": SESSION, "snapshot": snapshot}],
            [{"sessionId": SESSION, "state": state}], [(SESSION, FORECAST)])


def run(journals=None, records=None, expected=None, *, as_of=150):
    default = make_case()
    return audit(default[0] if journals is None else journals,
                 default[1] if records is None else records,
                 default[2] if expected is None else expected, as_of=as_of)


def test_pending_linked_alert_near_expiry_requires_review_without_authority():
    result = run()
    # Target candle closes in 30s; pre-expiry review is expected even though
    # the forecast remains PENDING and no notification/order is authorized.
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["alertHealth"]["counts"]["EXPIRING_SOON_WARNING"] == 1
    assert result["forecastCounts"]["PENDING"] == 1
    assert result["declaredCount"] == 1
    assert result["resolvedNoncancelledKeys"] == []
    assert all(result[key] is False for key in (
        "sourceAuthenticated", "providerDeliveryVerified", "maySendNotification",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_empty_is_not_green():
    result = audit([], [], [], as_of=150)
    assert result["status"] == "NO_DECLARED_ALERTS"
    assert result["declaredCount"] == 0


@pytest.mark.parametrize("status", ["QUEUED", "IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED"])
def test_settled_non_cancelled_requires_review(status):
    j, r, e = make_case(as_of=180, state_status=status, candle=120)
    result = audit(j, r, e, as_of=180)
    assert result["forecastCounts"]["SETTLED"] == 1
    assert result["forecastCounts"]["RESOLVED_NONCANCELLED"] == 1
    assert result["resolvedNoncancelledKeys"] == [[SESSION, FORECAST]]
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"


def test_settled_cancelled_not_misclassified_as_active():
    j, r, e = make_case(as_of=180, state_status="CANCELLED", candle=120)
    result = audit(j, r, e, as_of=180)
    assert result["forecastCounts"]["SETTLED"] == 1
    assert result["forecastCounts"]["RESOLVED_NONCANCELLED"] == 0


def test_gap_voided_alert_requires_review():
    j, r, e = make_case(as_of=240, candle=180)
    result = audit(j, r, e, as_of=240)
    assert result["forecastCounts"]["VOID_GAP"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"


@pytest.mark.parametrize("field,value", [
    ("issueSeq", 3), ("modelVersion", "other"), ("horizon", 3),
    ("baseStart", 0), ("issuedAt", 121),
    ("identity", {**FEED, "provider": "other"}),
])
def test_cross_store_mismatch_rejected(field, value):
    j, r, e = make_case()
    r[0]["state"][field] = value
    with pytest.raises(ValueError):
        audit(j, r, e, as_of=150)


@pytest.mark.parametrize("expiry", [181, 3721, 120])
def test_forged_expiry_rejected(expiry):
    j, r, e = make_case()
    r[0]["state"]["expiresAt"] = expiry
    with pytest.raises(ValueError):
        audit(j, r, e, as_of=150)


def test_orphaned_forecast_id_rejected():
    j, r, _ = make_case()
    r[0]["state"]["forecastId"] = "orphan"
    with pytest.raises(ValueError, match="Orphaned"):
        audit(j, r, [(SESSION, "orphan")], as_of=150)


def test_forged_derived_forecast_outcome_rejected():
    j, r, e = make_case()
    j[0]["snapshot"]["forecasts"][0]["status"] = "SETTLED"
    with pytest.raises(ValueError, match="replay"):
        audit(j, r, e, as_of=150)


def test_modified_issuance_event_rejected():
    j, r, e = make_case()
    j[0]["snapshot"]["events"][1]["probability"] = 0.8
    with pytest.raises(ValueError, match="replay"):
        audit(j, r, e, as_of=150)


@pytest.mark.parametrize("mutation", [
    lambda j: j[0]["snapshot"].update(sequence=True),
    lambda j: j[0]["snapshot"].update(sequence=5),
    lambda j: j[0]["snapshot"].update(evidence="AUTHENTICATED_LIVE"),
    lambda j: j[0]["snapshot"].update(extra=True),
    lambda j: j.append(copy.deepcopy(j[0])),
    lambda j: j[0].update(sessionId="other"),
])
def test_snapshot_population_rejected(mutation):
    j, r, e = make_case()
    mutation(j)
    with pytest.raises(ValueError):
        audit(j, r, e, as_of=150)


def test_missing_journal_session_rejected():
    _, r, e = make_case()
    with pytest.raises(ValueError, match="Incomplete"):
        audit([], r, e, as_of=150)


def test_missing_outbox_rejected_by_independent_inventory():
    j, _, e = make_case()
    with pytest.raises(ValueError, match="Incomplete"):
        audit(j, [], e, as_of=150)


def test_bound_and_type_validation():
    with pytest.raises(ValueError, match="bounded"):
        audit([None] * 1001, [], [], as_of=150)
    with pytest.raises(ValueError, match="bounded"):
        audit({}, [], [], as_of=150)


def test_no_mutation_of_caller_evidence():
    j, r, e = make_case()
    before = copy.deepcopy((j, r, e))
    audit(j, r, e, as_of=150)
    assert (j, r, e) == before
