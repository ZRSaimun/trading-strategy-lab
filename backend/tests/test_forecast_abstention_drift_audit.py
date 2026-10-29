"""Synthetic forecast/abstention drift tests: no external data or orders."""
from copy import deepcopy
import pytest

from app.forecast_abstention_drift_audit import audit_forecast_abstention_drift as audit

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "abstention-drift-test", "priceSide": "bid", "seconds": 60}


def keys(n=60, model="m1", horizon=1, offset=0):
    return [(model, horizon, 60 * (i + 1 + offset)) for i in range(n)]


def abstain(key, reason="LOW_CONFIDENCE"):
    model, horizon, base = key
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60, "reason": reason}


def snapshot(selected):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(selected):
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": .6,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": .6, "baseStart": base, "baseClose": 100.,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": 30, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def evaluate(expected, absent=(), **kwargs):
    absent = list(absent)
    excluded = {(a["modelVersion"], a["horizon"], a["baseStart"]) for a in absent}
    s = snapshot([k for k in expected if k not in excluded])
    return audit(s, IDENTITY, expected, absent,
                 as_of=max((k[2] for k in expected), default=0) + 120, **kwargs)


def test_complete_60_forecasts_no_abstention_is_unverified():
    expected = keys()
    r = evaluate(expected)
    assert r["status"] == "DECLARED_ABSTENTION_MIX_WITHIN_WARNING_UNVERIFIED"
    assert r["eligibleModelHorizonGroups"] == 1
    assert r["maxAbsoluteDeclaredAbstentionRateChange"] == 0
    assert r["byModelHorizon"][0]["earlyCount"] == 30
    assert r["byModelHorizon"][0]["lateCount"] == 30
    assert all(r[k] is False for k in ("sourceAuthenticated", "decisionClockAuthenticated",
        "scheduleIndependentlyVerified", "abstentionsIndependentlyVerified",
        "recipientDeliveryVerified", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_late_abstention_regime_jump_requires_review():
    expected = keys()
    r = evaluate(expected, [abstain(k) for k in expected[30:]])
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["groupsWithWarning"] == 1
    g = r["byModelHorizon"][0]
    assert (g["earlyAbstentions"], g["lateAbstentions"]) == (0, 30)
    assert g["lateMinusEarlyAbstentionRate"] == 1
    assert g["lateReasons"]["LOW_CONFIDENCE"] == 30


def test_negative_drift_and_reason_breakdown():
    expected = keys()
    absent = [abstain(k, "DATA_QUALITY") for k in expected[:15]]
    r = evaluate(expected, absent)
    g = r["byModelHorizon"][0]
    assert g["lateMinusEarlyAbstentionRate"] == -.5
    assert g["earlyReasons"]["DATA_QUALITY"] == 15
    assert r["groupsWithWarning"] == 1


def test_boundary_equal_threshold_is_not_a_warning():
    expected = keys()
    r = evaluate(expected, [abstain(k) for k in expected[30:36]], warning_fraction=.2)
    assert r["groupsWithWarning"] == 0
    assert r["byModelHorizon"][0]["lateMinusEarlyAbstentionRate"] == pytest.approx(.2)


def test_chronology_sorted_independent_of_input_order():
    expected = keys()
    absent = [abstain(k) for k in expected[:12]]
    forward = evaluate(expected, absent)
    reverse = evaluate(list(reversed(expected)), list(reversed(absent)))
    assert forward == reverse


def test_odd_population_splits_floor_then_ceiling():
    expected = keys(61)
    r = evaluate(expected, [abstain(expected[-1])])
    g = r["byModelHorizon"][0]
    assert (g["earlyCount"], g["lateCount"]) == (30, 31)
    assert g["lateAbstentionRate"] == pytest.approx(1/31)


def test_separate_model_horizon_no_pooled_mixing():
    expected = keys(60, "m1", 1) + keys(60, "m2", 12)
    r = evaluate(expected, [abstain(k) for k in expected[90:]])
    assert r["eligibleModelHorizonGroups"] == 2
    assert r["groupsWithWarning"] == 1
    assert [(g["modelVersion"], g["horizonCandles"]) for g in r["byModelHorizon"]] == [("m1", 1), ("m2", 12)]


def test_short_complete_group_withholds_rates():
    r = evaluate(keys(59))
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["eligibleModelHorizonGroups"] == 0
    assert r["insufficientModelHorizonGroups"] == 1
    assert r["maxAbsoluteDeclaredAbstentionRateChange"] is None


def test_missing_expected_decision_withholds_all_rates():
    expected = keys()
    r = audit(snapshot(expected[:-1]), IDENTITY, expected, [], as_of=4000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["byModelHorizon"] == []
    assert r["groupsWithWarning"] is None
    assert r["insufficientModelHorizonGroups"] is None


def test_conflict_withholds_all_rates():
    expected = keys()
    r = audit(snapshot(expected), IDENTITY, expected, [abstain(expected[0])], as_of=4000)
    assert r["byModelHorizon"] == []
    assert r["maxAbsoluteDeclaredAbstentionRateChange"] is None


def test_unexpected_forecast_withholds_all_rates():
    expected = keys()
    r = audit(snapshot(expected + [("other", 1, 3660)]), IDENTITY, expected, [], as_of=4000)
    assert r["byModelHorizon"] == []


def test_empty_expected_never_claims_stability():
    r = evaluate([])
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["byModelHorizon"] == []


def test_input_not_mutated():
    expected = keys()
    s = snapshot(expected[:30])
    absent = [abstain(k) for k in expected[30:]]
    before = deepcopy((s, expected, absent))
    audit(s, IDENTITY, expected, absent, as_of=4000)
    assert (s, expected, absent) == before


@pytest.mark.parametrize("minimum,threshold", [(True, .2), (29, .2), (2501, .2),
    (30., .2), (30, True), (30, -0.1), (30, 1.1), (30, float("nan")),
    (30, float("inf")), (30, "0.2")])
def test_invalid_configuration_rejected(minimum, threshold):
    with pytest.raises(ValueError):
        evaluate(keys(), min_per_half=minimum, warning_fraction=threshold)


def test_invalid_source_or_abstention_rejected_by_underlying_census():
    expected = keys()
    s = snapshot(expected)
    s["evidence"] = "AUTHENTICATED_LIVE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, [], as_of=4000)
    with pytest.raises(ValueError):
        audit(snapshot(expected[:-1]), IDENTITY, expected,
              [dict(abstain(expected[-1]), decisionAt=True)], as_of=4000)
