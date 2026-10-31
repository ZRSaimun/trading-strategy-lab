"""Synthetic, zero-network regression tests for abstention reason mix drift."""
from copy import deepcopy
import pytest

from app import forecast_abstention_reason_mix_audit as module

IDENTITY = {"instrument": "SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "reason-mix", "priceSide": "bid", "seconds": 60}


def keys(n=120, model="m1", horizon=1, offset=0):
    return [(model, horizon, (i + offset + 1) * 60) for i in range(n)]


def abstain(k, reason="LOW_CONFIDENCE"):
    model, horizon, base = k
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60, "reason": reason}


def fake_coverage(snapshot, identity, expected, abstentions, *, as_of):
    if identity != IDENTITY or type(as_of) is not int:
        raise ValueError("Bad identity or cutoff")
    exp = set(expected)
    abst = {(a["modelVersion"], a["horizon"], a["baseStart"]) for a in abstentions}
    if len(exp) != len(expected) or len(abst) != len(abstentions):
        raise ValueError("Duplicate")
    if not exp:
        status = "NO_DECLARED_EXPECTATIONS"
    elif abst == exp:
        status = "DECLARED_DECISIONS_MATCH_UNVERIFIED"
    else:
        status = "OPERATOR_REVIEW_REQUIRED"
    return {"status": status, "expectedCount": len(exp)}


@pytest.fixture(autouse=True)
def stub_validated_decision_coverage(monkeypatch):
    # Full repository CI separately exercises the actual coverage validator.
    monkeypatch.setattr(module, "audit_forecast_decision_coverage", fake_coverage)


def evaluate(expected=None, reason=None, **kwargs):
    expected = keys() if expected is None else expected
    reason = reason or (lambda k: "LOW_CONFIDENCE")
    return module.audit_forecast_abstention_reason_mix(
        {}, IDENTITY, expected, [abstain(k, reason(k)) for k in expected],
        as_of=max((k[2] for k in expected), default=0) + 120, **kwargs)


def test_stable_complete_reason_mix_is_unverified():
    r = evaluate()
    assert r["status"] == "DECLARED_REASON_MIX_WITHIN_WARNING_UNVERIFIED"
    assert r["maxTotalVariation"] == 0
    assert r["groupsWithWarning"] == 0
    assert r["byModelHorizon"][0]["earlyAbstentionCount"] == 60
    assert all(r[k] is False for k in (
        "sourceAuthenticated", "scheduleIndependentlyVerified",
        "abstentionsIndependentlyVerified", "forecastOutcomesAuthenticated",
        "recipientDeliveryVerified", "maySendNotification",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_disjoint_reasons_warn_at_max_distance():
    r = evaluate(reason=lambda k: "DATA_QUALITY" if k[2] <= 3600 else "POLICY_HOLD")
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["maxTotalVariation"] == 1
    assert r["groupsWithWarning"] == 1


def test_equal_threshold_does_not_warn():
    r = evaluate(reason=lambda k: "DATA_QUALITY" if k[2] <= 3600 else "POLICY_HOLD",
                 warning_total_variation=1)
    assert r["groupsWithWarning"] == 0


def test_partial_reason_shift():
    r = evaluate(reason=lambda k: "DATA_QUALITY" if k[2] <= 3600 or k[2] > 5400
                 else "LOW_CONFIDENCE")
    assert r["maxTotalVariation"] == pytest.approx(.5)


def test_odd_split_is_chronological():
    r = evaluate(keys(121))
    g = r["byModelHorizon"][0]
    assert (g["earlyDecisionCount"], g["lateDecisionCount"]) == (60, 61)
    assert g["lateLastBaseStart"] == 7260


def test_multiple_models_and_horizons_isolated():
    expected = keys(model="a") + keys(model="b", horizon=12)
    r = evaluate(expected, reason=lambda k: ("DATA_QUALITY" if k[2] <= 3600 else
                 "POLICY_HOLD") if k[0] == "b" else "LOW_CONFIDENCE")
    assert r["eligibleModelHorizonGroups"] == 2
    assert r["groupsWithWarning"] == 1
    assert [g["modelVersion"] for g in r["byModelHorizon"]] == ["a", "b"]


def test_order_invariance_and_no_mutation():
    expected = keys()
    absent = [abstain(k) for k in expected]
    original = deepcopy((expected, absent))
    a = module.audit_forecast_abstention_reason_mix({}, IDENTITY, expected, absent, as_of=8000)
    b = module.audit_forecast_abstention_reason_mix({}, IDENTITY, list(reversed(expected)),
                                                     list(reversed(absent)), as_of=8000)
    assert a == b
    assert (expected, absent) == original


def test_insufficient_decisions_withholds_group():
    r = evaluate(keys(59))
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["maxTotalVariation"] is None
    assert r["groupsWithWarning"] == 0


def test_incomplete_census_suppresses_all_groups():
    expected = keys()
    r = module.audit_forecast_abstention_reason_mix({}, IDENTITY, expected,
        [abstain(k) for k in expected[:-1]], as_of=8000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["byModelHorizon"] == []
    assert r["groupsWithWarning"] is None


def test_empty_census_is_not_stability():
    r = evaluate([])
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["maxTotalVariation"] is None


@pytest.mark.parametrize("d,a,t", [
    (True,20,.25),(29,20,.25),(2501,20,.25),(30.,20,.25),
    (30,True,.25),(30,19,.25),(30,2501,.25),(30,20.,.25),
    (30,20,True),(30,20,-.1),(30,20,1.1),(30,20,float('nan')),
    (30,20,float('inf')),(30,20,'0.25')])
def test_invalid_thresholds_fail_closed(d,a,t):
    with pytest.raises(ValueError):
        evaluate(min_decisions_per_half=d, min_abstentions_per_half=a,
                 warning_total_variation=t)


def test_bad_coverage_exception_propagates():
    with pytest.raises(ValueError):
        module.audit_forecast_abstention_reason_mix({}, {"wrong": "identity"},
            keys(), [abstain(k) for k in keys()], as_of=8000)
