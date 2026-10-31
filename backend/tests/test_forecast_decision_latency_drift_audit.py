"""Synthetic chronological decision latency drift tests; no network or orders."""
from copy import deepcopy
import pytest

from app.forecast_decision_latency_drift_audit import (
    audit_forecast_decision_latency_drift as audit)

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "latency-drift-test", "priceSide": "bid", "seconds": 60}


def keys(n=60, model="m1", horizon=1, offset=0):
    return [(model, horizon, (i + offset + 1) * 60) for i in range(n)]


def abstain(key, lag=0):
    model, horizon, base = key
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60 + lag, "reason": "LOW_CONFIDENCE"}


def snapshot(selected, lag=lambda k: 0):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(selected):
        at = base + 60 + lag((model, horizon, base))
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": .6,
                       "baseStart": base, "receivedAt": at})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": .6, "baseStart": base, "baseClose": 100.,
                          "issuedAt": at, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": 30, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def evaluate(expected, *, lag=lambda k: 0, abstentions=(), **kwargs):
    abstentions = list(abstentions)
    absent = {(a["modelVersion"], a["horizon"], a["baseStart"]) for a in abstentions}
    return audit(snapshot([k for k in expected if k not in absent], lag),
                 IDENTITY, expected, abstentions,
                 as_of=max((k[2] for k in expected), default=0) + 120, **kwargs)


def test_stable_complete_population_is_unverified_not_permission():
    r = evaluate(keys())
    assert r["status"] == "DECLARED_LATENCY_DRIFT_WITHIN_WARNING_UNVERIFIED"
    assert r["eligibleModelHorizonGroups"] == 1
    assert r["groupsWithP95IncreaseWarning"] == 0
    assert r["maxP95IncreaseSeconds"] == 0
    assert all(r[k] is False for k in (
        "sourceAuthenticated", "decisionClockAuthenticated",
        "scheduleIndependentlyVerified", "abstentionsIndependentlyVerified",
        "recipientDeliveryVerified", "maySendNotification",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_rising_p95_detected_without_claiming_statistical_drift():
    expected = keys()
    r = evaluate(expected, lag=lambda k: 20 if k[2] > 1800 else 0)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["groupsWithP95IncreaseWarning"] == 1
    g = r["byModelHorizon"][0]
    assert (g["earlyP95DeclaredLatencySeconds"], g["lateP95DeclaredLatencySeconds"]) == (0, 20)
    assert (g["earlyLateDecisionCount"], g["lateLateDecisionCount"]) == (0, 30)


def test_equal_threshold_not_warning():
    expected = keys()
    r = evaluate(expected, lag=lambda k: 10 if k[2] > 1800 else 0)
    assert r["groupsWithP95IncreaseWarning"] == 0
    assert r["maxP95IncreaseSeconds"] == 10


def test_improving_latency_not_a_regression_warning():
    r = evaluate(keys(), lag=lambda k: 20 if k[2] <= 1800 else 0)
    assert r["maxP95IncreaseSeconds"] == -20
    assert r["groupsWithP95IncreaseWarning"] == 0


def test_odd_group_uses_chronological_floor_ceiling():
    expected = keys(61)
    r = evaluate(expected, lag=lambda k: 20 if k == expected[-1] else 0)
    g = r["byModelHorizon"][0]
    assert (g["earlyCount"], g["lateCount"]) == (30, 31)
    assert g["lateP95DeclaredLatencySeconds"] == 0


def test_mixed_forecasts_abstentions_contribute_to_latency():
    expected = keys()
    absent = [abstain(k, lag=20) for k in expected[30:]]
    r = evaluate(expected, abstentions=absent)
    assert r["groupsWithP95IncreaseWarning"] == 1
    assert r["byModelHorizon"][0]["lateP95DeclaredLatencySeconds"] == 20


def test_separate_model_and_horizon_cohorts():
    expected = keys(60, "m1", 1) + keys(60, "m2", 12)
    r = evaluate(expected, lag=lambda k: 20 if k[0] == "m2" and k[2] > 1800 else 0)
    assert r["eligibleModelHorizonGroups"] == 2
    assert r["groupsWithP95IncreaseWarning"] == 1
    assert [(g["modelVersion"], g["horizonCandles"]) for g in r["byModelHorizon"]] == [
        ("m1", 1), ("m2", 12)]


def test_order_invariant_and_no_mutation():
    expected = keys()
    s = snapshot(expected)
    before = deepcopy((s, expected))
    a = audit(s, IDENTITY, expected, [], as_of=4000)
    b = audit(s, IDENTITY, list(reversed(expected)), [], as_of=4000)
    assert a == b
    assert (s, expected) == before


def test_short_complete_group_withholds_percentiles():
    r = evaluate(keys(59))
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["byModelHorizon"] == []
    assert r["maxP95IncreaseSeconds"] is None


def test_missing_decision_withholds_all_group_results():
    expected = keys()
    r = audit(snapshot(expected[:-1]), IDENTITY, expected, [], as_of=4000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["byModelHorizon"] == []
    assert r["groupsWithP95IncreaseWarning"] is None


def test_conflicting_abstention_withholds_all_group_results():
    expected = keys()
    r = audit(snapshot(expected), IDENTITY, expected, [abstain(expected[0])], as_of=4000)
    assert r["byModelHorizon"] == []


def test_unexpected_forecast_withholds_all_group_results():
    expected = keys()
    r = audit(snapshot(expected + [("other", 1, 3660)]), IDENTITY, expected, [],
              as_of=4000)
    assert r["byModelHorizon"] == []


def test_empty_population_never_claims_stability():
    r = evaluate([])
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["byModelHorizon"] == []


@pytest.mark.parametrize("minimum,increase,lateness", [
    (True, 10, 15), (29, 10, 15), (2501, 10, 15),
    (30., 10, 15), (30, True, 15), (30, -1, 15),
    (30, 3601, 15), (30, 10., 15), (30, 10, True),
    (30, 10, -1), (30, 10, 31), (30, 10, 15.)])
def test_invalid_parameters_fail_closed(minimum, increase, lateness):
    with pytest.raises(ValueError):
        evaluate(keys(), min_per_half=minimum,
                 warning_increase_seconds=increase,
                 decision_warning_seconds=lateness)


def test_forged_evidence_and_invalid_abstention_rejected():
    expected = keys()
    s = snapshot(expected)
    s["evidence"] = "VERIFIED_LIVE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, [], as_of=4000)
    with pytest.raises(ValueError):
        audit(snapshot(expected[:-1]), IDENTITY, expected,
              [dict(abstain(expected[-1]), decisionAt=True)], as_of=4000)
