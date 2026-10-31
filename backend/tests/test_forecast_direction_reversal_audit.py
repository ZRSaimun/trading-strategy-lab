"""Synthetic disconnected direction-reversal regressions; no external services."""
from copy import deepcopy
import random

import pytest

from app.forecast_direction_reversal_audit import (
    _direction, _transitions, audit_forecast_direction_reversals as audit)

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "direction-test", "priceSide": "bid", "seconds": 60}


def fixture(probs, *, abstained=(), bases=None, horizon=1, model="m1"):
    if bases is None:
        bases = [60 * (i + 1) for i in range(len(probs))]
    events, forecasts, abstentions = [], [], []
    for i, (base, p) in enumerate(zip(bases, probs)):
        if i in abstained:
            abstentions.append({"modelVersion": model, "horizon": horizon,
                                "baseStart": base, "decisionAt": base + 60,
                                "reason": "LOW_CONFIDENCE"})
            continue
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": p, "baseStart": base,
                       "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": p, "baseStart": base, "baseClose": 100.,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return ({"sequence": len(events), "identity": deepcopy(IDENTITY),
             "maxLagSeconds": 30, "events": events, "forecasts": forecasts,
             "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"},
            [(model, horizon, b) for b in bases], abstentions)


def run(probs, *, abstained=(), bases=None, **kwargs):
    s, expected, a = fixture(probs, abstained=abstained, bases=bases)
    return audit(s, IDENTITY, expected, a, as_of=100000, **kwargs)


def test_alternating_direction_flags_and_is_read_only():
    s, expected, a = fixture([.2, .8] * 40)
    before = deepcopy(s)
    r = audit(s, IDENTITY, expected, a, as_of=100000)
    assert s == before
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    g = r["byModelHorizon"][0]
    assert (g["eligibleAdjacentSignedPairs"], g["directionReversalCount"],
            g["strongReversalCount"]) == (79, 79, 79)
    assert g["longestConsecutiveReversalPairs"] == 79
    assert g["longestReversalRunBaseStarts"] == [60, 4800]
    assert g["trailingConsecutiveReversalPairs"] == 79
    assert g["directionReversalFractionOfEligiblePairs"] == 1
    assert all(r[k] is False for k in ("sourceAuthenticated", "scheduleIndependentlyVerified",
        "abstentionsIndependentlyVerified", "forecastOutcomesAuthenticated",
        "recipientDeliveryVerified", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_stable_direction_no_warning():
    r = run([.7 + .001 * (i % 10) for i in range(80)])
    assert r["status"] == "DECLARED_DIRECTION_REVERSALS_WITHIN_WARNING_UNVERIFIED"
    g = r["byModelHorizon"][0]
    assert g["directionReversalCount"] == 0
    assert g["eligibleAdjacentSignedPairs"] == 79
    assert g["largestAdjacentSignedProbabilityJump"] > 0
    assert not g["reversalFractionMeetsWarning"]


def test_abstention_breaks_transition_and_run():
    r = run([.2, .8] * 40, abstained=(40,))
    g = r["byModelHorizon"][0]
    assert g["abstentionCount"] == 1
    assert g["eligibleAdjacentSignedPairs"] == 77
    assert g["longestConsecutiveReversalPairs"] == 39
    assert g["trailingConsecutiveReversalPairs"] == 38


def test_missing_expected_calendar_breaks_transition():
    bases = [60 * (i + 1) for i in range(40)] + [60 * (i + 3) for i in range(40, 80)]
    g = run([.2, .8] * 40, bases=bases)["byModelHorizon"][0]
    assert g["eligibleAdjacentSignedPairs"] == 78
    assert g["longestConsecutiveReversalPairs"] == 39


def test_neutral_and_boundary_are_not_directional():
    assert [_direction(p, .05) for p in (.44, .45, .5, .55, .56)] == [-1, 0, 0, 0, 1]
    p = [.2, .8] * 40
    p[30] = .5
    g = run(p)["byModelHorizon"][0]
    assert g["neutralForecastCount"] == 1
    assert g["eligibleAdjacentSignedPairs"] == 77
    assert g["directionReversalCount"] == 77


def test_strong_reversal_requires_both_endpoints():
    p = [.43, .57] * 40
    g = run(p)["byModelHorizon"][0]
    assert g["directionReversalCount"] == 79
    assert g["strongReversalCount"] == 0


def test_exact_warning_threshold_inclusive():
    p = [.2] * 60
    for i in range(1, 60):
        if i % 2 == 1 and i <= 30:
            p[i] = .8
    g = run(p, warning_reversal_fraction=.1)["byModelHorizon"][0]
    assert g["reversalFractionMeetsWarning"]
    assert g["directionReversalCount"] == 30


def test_insufficient_decisions_withholds():
    r = run([.2, .8] * 20)
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["byModelHorizon"] == []


def test_insufficient_signed_pairs_withholds():
    r = run([.5] * 80)
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["byModelHorizon"] == []


def test_missing_decision_withholds_all():
    s, expected, a = fixture([.2, .8] * 40)
    s["events"].pop(); s["forecasts"].pop(); s["sequence"] -= 1
    r = audit(s, IDENTITY, expected, a, as_of=100000)
    assert r["byModelHorizon"] == []
    assert r["groupsWithWarning"] is None


def test_conflicting_decision_withholds_all():
    s, expected, a = fixture([.2, .8] * 40)
    a.append({"modelVersion": "m1", "horizon": 1, "baseStart": 60,
              "decisionAt": 120, "reason": "OTHER"})
    assert audit(s, IDENTITY, expected, a, as_of=100000)["byModelHorizon"] == []


def test_unexpected_decision_withholds_all():
    s, expected, a = fixture([.2, .8] * 40)
    assert audit(s, IDENTITY, expected[:-1], a, as_of=100000)["byModelHorizon"] == []


def test_empty_expected_schedule():
    s, expected, a = fixture([])
    assert audit(s, IDENTITY, expected, a, as_of=100000)["status"] == "NO_DECLARED_EXPECTATIONS"


def test_horizon_12_is_descriptive_without_settlement():
    s, expected, a = fixture([.2, .8] * 40, horizon=12)
    assert audit(s, IDENTITY, expected, a, as_of=100000)["byModelHorizon"][0]["horizonCandles"] == 12


def test_malformed_thresholds_fail_closed():
    s, expected, a = fixture([.2, .8] * 40)
    for options in ({"min_decisions_per_group": True}, {"min_adjacent_signed_pairs": 29},
                    {"neutral_band": .2, "strong_band": .1},
                    {"neutral_band": float("nan")}, {"strong_band": .5},
                    {"warning_reversal_fraction": -1}, {"warning_reversal_fraction": True}):
        with pytest.raises(ValueError):
            audit(s, IDENTITY, expected, a, as_of=100000, **options)


def test_forged_live_evidence_rejected():
    s, expected, a = fixture([.2, .8] * 40)
    s["evidence"] = "LIVE_EXECUTABLE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, a, as_of=100000)


def test_identity_mismatch_rejected():
    s, expected, a = fixture([.2, .8] * 40)
    with pytest.raises(ValueError):
        audit(s, {**IDENTITY, "priceSide": "ask"}, expected, a, as_of=100000)


def test_bad_probability_rejected():
    s, expected, a = fixture([.2, .8] * 40)
    s["forecasts"][0]["probability"] = float("nan")
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, a, as_of=100000)


def test_transition_counts_randomized_bruteforce():
    rng = random.Random(61)
    for _ in range(250):
        bases, probs = [], {}
        t = 0
        for _ in range(80):
            t += rng.choice((60, 60, 120))
            bases.append(t)
            if rng.randrange(5):
                probs[t] = rng.choice((.2, .45, .5, .55, .8))
        actual = _transitions(bases, probs, 60, .05, .1)
        pairs = [(probs[bases[i - 1]], probs[bases[i]])
                 for i in range(1, len(bases))
                 if bases[i] - bases[i - 1] == 60
                 and _direction(probs.get(bases[i - 1]), .05)
                 and _direction(probs.get(bases[i]), .05)]
        assert actual["eligibleAdjacentSignedPairs"] == len(pairs)
        assert actual["directionReversalCount"] == sum(
            _direction(a, .05) != _direction(b, .05) for a, b in pairs)
        assert actual["strongReversalCount"] == sum(
            _direction(a, .05) != _direction(b, .05)
            and abs(a - .5) >= .1 and abs(b - .5) >= .1 for a, b in pairs)
