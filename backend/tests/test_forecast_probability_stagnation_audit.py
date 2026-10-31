"""Synthetic offline regression tests: no network, broker or market access."""
from copy import deepcopy

import pytest

from app.forecast_probability_stagnation_audit import (
    _run_lengths, audit_forecast_probability_stagnation as audit)

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "stagnation-test", "priceSide": "bid", "seconds": 60}


def fixture(probs, *, abstained=(), model="m1", horizon=1, bases=None):
    if bases is None:
        bases = [60 * (i + 1) for i in range(len(probs))]
    expected = [(model, horizon, b) for b in bases]
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
    snapshot = {"sequence": len(events), "identity": deepcopy(IDENTITY),
                "maxLagSeconds": 30, "events": events, "forecasts": forecasts,
                "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}
    return snapshot, expected, abstentions


def run(probs, *, abstained=(), bases=None, **kwargs):
    snap, expected, abstentions = fixture(probs, abstained=abstained, bases=bases)
    return audit(snap, IDENTITY, expected, abstentions, as_of=10000, **kwargs)


def test_stuck_constant_output_warns_and_does_not_authorize():
    s, expected, abstentions = fixture([0.6] * 40)
    before = deepcopy(s)
    r = audit(s, IDENTITY, expected, abstentions, as_of=10000)
    assert s == before
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    g = r["byModelHorizon"][0]
    assert (g["forecastCount"], g["distinctExactProbabilityCount"]) == (40, 1)
    assert (g["longestIdenticalProbabilityStreak"], g["trailingIdenticalProbabilityStreak"]) == (40, 40)
    assert g["longestIdenticalProbabilityStreakBaseStarts"] == [60, 2400]
    assert g["dominantExactProbabilityFraction"] == 1.0
    assert all(r[k] is False for k in ("sourceAuthenticated", "scheduleIndependentlyVerified",
        "forecastOutputsIndependentlyVerified", "recipientDeliveryVerified",
        "maySendNotification", "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_varied_output_passes_descriptive_threshold():
    r = run([0.2 + i * .01 for i in range(40)])
    assert r["status"] == "DECLARED_PROBABILITY_VARIATION_WITHIN_WARNING_UNVERIFIED"
    g = r["byModelHorizon"][0]
    assert g["distinctExactProbabilityCount"] == 40
    assert g["longestIdenticalProbabilityStreak"] == 1
    assert g["trailingIdenticalProbabilityStreak"] == 1
    assert not g["operatorReviewWarning"]


def test_abstention_breaks_runs_and_is_not_a_forecast():
    r = run([.6] * 15 + [.2] * 10 + [.6] * 15, abstained=(14, 25),
            warning_consecutive_identical=15, warning_dominance_percent=100)
    g = r["byModelHorizon"][0]
    assert g["abstentionCount"] == 2
    assert g["longestIdenticalProbabilityStreak"] == 14
    assert g["trailingIdenticalProbabilityStreak"] == 14
    assert not g["streakWarning"]


def test_expected_calendar_gap_breaks_run():
    bases = [60 * (i + 1) for i in range(20)] + [60 * (i + 3) for i in range(20, 40)]
    r = run([.6] * 40, bases=bases, warning_consecutive_identical=30)
    assert r["byModelHorizon"][0]["longestIdenticalProbabilityStreak"] == 20


def test_dominance_can_warn_without_long_consecutive_run():
    p = [.6] * 39 + [.7]
    p[20], p[-1] = p[-1], p[20]
    r = run(p, warning_consecutive_identical=30)
    g = r["byModelHorizon"][0]
    assert not g["streakWarning"]
    assert g["dominanceWarning"]
    assert g["dominantExactProbabilityCount"] == 39


def test_exact_threshold_inclusive():
    r = run([.6] * 36 + [.7] * 4, warning_consecutive_identical=40)
    assert r["byModelHorizon"][0]["dominanceWarning"]


def test_below_support_withholds_metrics():
    r = run([.6] * 29)
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["byModelHorizon"] == []
    assert r["groupsWithWarning"] == 0


def test_abstentions_can_reduce_forecast_support():
    r = run([.6] * 40, abstained=tuple(range(11)))
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"


def test_missing_decision_withholds_every_group():
    s, expected, a = fixture([.6] * 40)
    s["forecasts"].pop()
    s["events"].pop()
    s["sequence"] -= 1
    r = audit(s, IDENTITY, expected, a, as_of=10000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["byModelHorizon"] == []
    assert r["groupsWithWarning"] is None


def test_conflicting_abstention_withholds_every_group():
    s, expected, a = fixture([.6] * 40)
    a.append({"modelVersion": "m1", "horizon": 1, "baseStart": 60,
              "decisionAt": 120, "reason": "OTHER"})
    assert audit(s, IDENTITY, expected, a, as_of=10000)["byModelHorizon"] == []


def test_unexpected_forecast_withholds():
    s, expected, a = fixture([.6] * 40)
    assert audit(s, IDENTITY, expected[:-1], a, as_of=10000)["byModelHorizon"] == []


def test_empty_schedule_no_certification():
    s, expected, a = fixture([])
    r = audit(s, IDENTITY, expected, a, as_of=10000)
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"


def test_exact_probability_avoids_arbitrary_near_match():
    r = run([.6, .6000000000000001] * 20)
    assert r["byModelHorizon"][0]["distinctExactProbabilityCount"] == 2
    assert r["byModelHorizon"][0]["longestIdenticalProbabilityStreak"] == 1


def test_horizon_12_supported_without_settlement():
    s, expected, a = fixture([.5] * 40, horizon=12)
    r = audit(s, IDENTITY, expected, a, as_of=10000)
    assert r["byModelHorizon"][0]["horizonCandles"] == 12


def test_last_abstention_clears_trailing_run():
    r = run([.6] * 40, abstained=(39,))
    assert r["byModelHorizon"][0]["trailingIdenticalProbabilityStreak"] == 0


def test_threshold_strict_type_and_range():
    s, expected, a = fixture([.6] * 40)
    for options in ({"min_decisions_per_group": True},
                    {"min_forecasts_per_group": 29},
                    {"warning_consecutive_identical": 1},
                    {"warning_dominance_percent": 101},
                    {"warning_dominance_percent": 90.0}):
        with pytest.raises(ValueError):
            audit(s, IDENTITY, expected, a, as_of=10000, **options)


def test_forged_feed_evidence_rejected():
    s, expected, a = fixture([.6] * 40)
    s["evidence"] = "LIVE_EXECUTABLE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, a, as_of=10000)


def test_source_identity_mismatch_rejected():
    s, expected, a = fixture([.6] * 40)
    with pytest.raises(ValueError):
        audit(s, {**IDENTITY, "priceSide": "ask"}, expected, a, as_of=10000)


def test_invalid_probability_rejected_by_scorecard():
    s, expected, a = fixture([.6] * 40)
    s["forecasts"][0]["probability"] = float("nan")
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, a, as_of=10000)


def test_run_lengths_bruteforce_randomized():
    import random
    rng = random.Random(0)
    for _ in range(300):
        bases = []
        t = 60
        probs = {}
        for i in range(40):
            t += 60 * rng.choice((1, 1, 1, 2))
            bases.append(t)
            if rng.randrange(4):
                probs[t] = rng.choice((.2, .5, .8))
        longest, bounds, trailing = _run_lengths(bases, probs, 60)
        runs = []
        run = []
        for b in bases:
            if b in probs:
                if run and b - run[-1] == 60 and probs[b] == probs[run[-1]]:
                    run.append(b)
                else:
                    run = [b]
                runs.append(run[:])
            else:
                run = []
        maximum = max((len(v) for v in runs), default=0)
        assert longest == maximum
        assert trailing == len(run)
        if longest:
            assert bounds in [[v[0], v[-1]] for v in runs if len(v) == longest]
        else:
            assert bounds is None
