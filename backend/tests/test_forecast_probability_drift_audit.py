"""Zero-network synthetic tests for declared forecast probability distribution drift."""
from copy import deepcopy
import math
import pytest

from app.forecast_probability_drift_audit import (
    audit_forecast_probability_drift as audit, _jensen_shannon_nats)

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "probability-drift-test", "priceSide": "bid", "seconds": 60}


def keys(n=60, model="m1", horizon=1, offset=0):
    return [(model, horizon, (i + offset + 1) * 60) for i in range(n)]


def abstain(key):
    model, horizon, base = key
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60, "reason": "LOW_CONFIDENCE"}


def snapshot(selected, probability=lambda k: .6):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(selected):
        p = probability((model, horizon, base))
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": p,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": p, "baseStart": base, "baseClose": 100.,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": 30, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def evaluate(expected, *, absent=(), probability=lambda k: .6, **kwargs):
    absent = list(absent)
    omitted = {(a["modelVersion"], a["horizon"], a["baseStart"]) for a in absent}
    return audit(snapshot([k for k in expected if k not in omitted], probability),
                 IDENTITY, expected, absent,
                 as_of=max((k[2] for k in expected), default=0) + 120, **kwargs)


def test_stable_complete_distribution_is_declared_only():
    r = evaluate(keys())
    assert r["status"] == "DECLARED_PROBABILITY_MIX_WITHIN_WARNING_UNVERIFIED"
    assert r["groupsWithWarning"] == 0
    assert r["maxJensenShannonNats"] == 0
    assert r["byModelHorizon"][0]["earlyFixedBinCounts"] == [0, 0, 0, 30, 0]
    assert all(r[k] is False for k in (
        "sourceAuthenticated", "scheduleIndependentlyVerified",
        "abstentionsIndependentlyVerified", "forecastOutcomesAuthenticated",
        "recipientDeliveryVerified", "maySendNotification",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_complete_disjoint_distributions_raise_warning():
    expected = keys()
    r = evaluate(expected, probability=lambda k: .9 if k[2] > 1800 else .1)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["groupsWithWarning"] == 1
    g = r["byModelHorizon"][0]
    assert g["earlyFixedBinCounts"] == [30, 0, 0, 0, 0]
    assert g["lateFixedBinCounts"] == [0, 0, 0, 0, 30]
    assert g["jensenShannonNats"] == pytest.approx(math.log(2))


def test_equal_threshold_does_not_warn():
    expected = keys()
    fn = lambda k: .9 if k[2] > 1800 else .1
    divergence = evaluate(expected, probability=fn)["maxJensenShannonNats"]
    r = evaluate(expected, probability=fn, warning_js_nats=divergence)
    assert r["groupsWithWarning"] == 0


def test_partial_shift_is_symmetric_and_bounded():
    a = _jensen_shannon_nats([15, 15, 0, 0, 0], [0, 15, 15, 0, 0])
    b = _jensen_shannon_nats([0, 15, 15, 0, 0], [15, 15, 0, 0, 0])
    assert a == pytest.approx(b)
    assert 0 < a < math.log(2)


def test_abstentions_in_denominator_but_not_histogram():
    expected = keys(120)
    missing = [abstain(k) for k in expected[30:60]]
    r = evaluate(expected, absent=missing)
    g = r["byModelHorizon"][0]
    assert (g["earlyDecisionCount"], g["lateDecisionCount"]) == (60, 60)
    assert (g["earlyForecastCount"], g["lateForecastCount"]) == (30, 60)
    assert (g["earlyAbstentionCount"], g["lateAbstentionCount"]) == (30, 0)
    assert (g["earlyAbstentionRate"], g["lateAbstentionRate"]) == (.5, 0)
    assert sum(g["earlyFixedBinCounts"]) == 30


def test_insufficient_forecasts_withholds_entire_group():
    expected = keys(120)
    missing = [abstain(k) for k in expected[:31]]
    r = evaluate(expected, absent=missing)
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["insufficientModelHorizonGroups"] == 1
    assert r["maxJensenShannonNats"] is None
    assert r["byModelHorizon"] == []


def test_insufficient_decisions_withholds_entire_group():
    r = evaluate(keys(59))
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["eligibleModelHorizonGroups"] == 0


def test_odd_chronological_population_uses_floor_ceiling():
    r = evaluate(keys(61))
    g = r["byModelHorizon"][0]
    assert (g["earlyDecisionCount"], g["lateDecisionCount"]) == (30, 31)
    assert g["lateLastBaseStart"] == 61 * 60


def test_model_and_horizon_isolation():
    expected = keys(60, "a", 1) + keys(60, "b", 12)
    r = evaluate(expected, probability=lambda k: (.9 if k[2] > 1800 else .1)
                 if k[0] == "b" else .6)
    assert r["eligibleModelHorizonGroups"] == 2
    assert r["groupsWithWarning"] == 1
    assert [(g["modelVersion"], g["horizonCandles"]) for g in r["byModelHorizon"]] == [
        ("a", 1), ("b", 12)]


def test_input_order_invariance_and_immutability():
    expected = keys(60)
    s = snapshot(expected, lambda k: .9 if k[2] > 1800 else .1)
    before = deepcopy((s, expected))
    first = audit(s, IDENTITY, expected, [], as_of=4000)
    second = audit(s, IDENTITY, list(reversed(expected)), [], as_of=4000)
    assert first == second
    assert (s, expected) == before


def test_missing_decision_suppresses_every_distribution():
    expected = keys()
    r = audit(snapshot(expected[:-1]), IDENTITY, expected, [], as_of=4000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["byModelHorizon"] == []
    assert r["groupsWithWarning"] is None


def test_conflicting_forecast_and_abstention_suppresses_distributions():
    expected = keys()
    r = audit(snapshot(expected), IDENTITY, expected, [abstain(expected[0])], as_of=4000)
    assert r["byModelHorizon"] == []


def test_unexpected_forecast_suppresses_distributions():
    expected = keys()
    r = audit(snapshot(expected + [("other", 1, 3660)]), IDENTITY, expected, [],
              as_of=4000)
    assert r["byModelHorizon"] == []


def test_empty_population_does_not_claim_stability():
    r = evaluate([])
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["byModelHorizon"] == []


def test_bins_cover_probability_boundaries():
    assert _jensen_shannon_nats([1, 1, 1, 1, 1], [1, 1, 1, 1, 1]) == 0
    expected = keys(60)
    vals = [.00001, .2, .4, .6, .8, .99999]
    r = evaluate(expected, probability=lambda k: vals[(k[2] // 60 - 1) % 6])
    g = r["byModelHorizon"][0]
    assert g["earlyFixedBinCounts"] == [5, 5, 5, 5, 10]
    assert g["lateFixedBinCounts"] == [5, 5, 5, 5, 10]


@pytest.mark.parametrize("minimum,forecasts,threshold", [
    (True, 30, .1), (29, 30, .1), (2501, 30, .1), (30., 30, .1),
    (30, True, .1), (30, 29, .1), (30, 2501, .1), (30, 30., .1),
    (30, 30, True), (30, 30, -.01), (30, 30, .7),
    (30, 30, float("nan")), (30, 30, float("inf")), (30, 30, "0.1")])
def test_invalid_configuration_fails_closed(minimum, forecasts, threshold):
    with pytest.raises(ValueError):
        evaluate(keys(), min_decisions_per_half=minimum,
                 min_forecasts_per_half=forecasts, warning_js_nats=threshold)


def test_forged_evidence_and_invalid_abstention_rejected():
    expected = keys()
    s = snapshot(expected)
    s["evidence"] = "VERIFIED_LIVE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, [], as_of=4000)
    with pytest.raises(ValueError):
        audit(snapshot(expected[:-1]), IDENTITY, expected,
              [dict(abstain(expected[-1]), decisionAt=True)], as_of=4000)
