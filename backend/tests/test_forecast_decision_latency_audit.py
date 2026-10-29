"""Synthetic completed-candle decision timing tests; no network or orders."""
from copy import deepcopy
import pytest

from app.forecast_decision_latency_audit import audit_forecast_decision_latency as audit

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "timing-test", "priceSide": "bid", "seconds": 60}


def keys(n=30):
    return [("m1", (1, 3, 12)[i % 3], 60 * (i + 1)) for i in range(n)]


def snapshot(selected, *, lag=30, offset=None):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(selected):
        at = base + 60 + (offset(i) if offset else 0)
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": .6,
                       "baseStart": base, "receivedAt": at})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": .6, "baseStart": base, "baseClose": 100.,
                          "issuedAt": at, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": lag, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def abstain(key, *, offset=0):
    model, horizon, base = key
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60 + offset, "reason": "LOW_CONFIDENCE"}


def test_complete_30_exact_closes_is_unverified_and_not_permission():
    expected = keys()
    s = snapshot(expected)
    before = deepcopy((s, expected))
    r = audit(s, IDENTITY, expected, [], as_of=4000)
    assert (s, expected) == before
    assert r["status"] == "DECLARED_TIMING_WITHIN_BUDGET_UNVERIFIED"
    assert r["p50DeclaredLatencySeconds"] == r["p95DeclaredLatencySeconds"] == 0
    assert r["withinBudgetFractionOfExpected"] == 1
    assert r["expectedCount"] == r["recordedExactlyOnceCount"] == 30
    assert all(r[k] is False for k in ("sourceAuthenticated", "decisionClockAuthenticated",
        "scheduleIndependentlyVerified", "abstentionsIndependentlyVerified",
        "recipientDeliveryVerified", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_nearest_rank_latency_and_warning_threshold_inclusive():
    expected = keys()
    r = audit(snapshot(expected, offset=lambda i: i), IDENTITY, expected, [],
              as_of=4000, warning_seconds=15)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["p50DeclaredLatencySeconds"] == 14
    assert r["p95DeclaredLatencySeconds"] == 28
    assert r["maxDeclaredLatencySeconds"] == 29
    assert r["lateRecordedDecisionCount"] == 14
    assert r["withinWarningBudgetCount"] == 16
    assert r["withinBudgetFractionOfExpected"] == pytest.approx(16 / 30)


def test_mixed_forecasts_abstentions_same_population_no_fake_wins():
    expected = keys()
    r = audit(snapshot(expected[:20]), IDENTITY, expected,
              [abstain(k, offset=10) for k in expected[20:]], as_of=4000)
    assert r["status"] == "DECLARED_TIMING_WITHIN_BUDGET_UNVERIFIED"
    assert r["recordedExactlyOnceCount"] == 30
    assert sum(row["recordedAbstentionCount"] for row in r["byHorizon"]) == 10
    assert r["p95DeclaredLatencySeconds"] == 10
    assert all(row["p95DeclaredLatencySeconds"] is None for row in r["byHorizon"])


def test_missing_not_overdue_before_deadline_but_overdue_after():
    expected = [("m1", 1, 60)]
    s = snapshot([])
    before = audit(s, IDENTITY, expected, [], as_of=120)
    after = audit(s, IDENTITY, expected, [], as_of=151)
    assert before["status"] == after["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert before["missingStillWithinWindowCount"] == 1
    assert before["missingPastDeadlineCount"] == 0
    assert after["missingStillWithinWindowCount"] == 0
    assert after["missingPastDeadlineCount"] == 1
    assert after["missingPastDeadlineKeysFirst50"] == [["m1", 1, 60]]
    assert before["p95DeclaredLatencySeconds"] is None


def test_missing_at_exact_deadline_not_yet_overdue():
    expected = [("m1", 1, 60)]
    assert audit(snapshot([]), IDENTITY, expected, [], as_of=150)["missingPastDeadlineCount"] == 0


def test_candle_window_stricter_than_lag_for_overdue_missing():
    expected = [("m1", 1, 60)]
    s = snapshot([], lag=60)
    r = audit(s, IDENTITY, expected, [], as_of=180, warning_seconds=15)
    assert r["missingPastDeadlineCount"] == 1


def test_conflicting_abstention_never_supplies_latency():
    expected = keys()
    r = audit(snapshot(expected), IDENTITY, expected, [abstain(expected[0])], as_of=4000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["p95DeclaredLatencySeconds"] is None
    assert r["recordedExactlyOnceCount"] == 29


def test_unexpected_forecast_withholds_complete_percentiles():
    expected = keys()
    other = ("other", 1, 2000)
    r = audit(snapshot(expected + [other]), IDENTITY, expected, [], as_of=4000)
    assert r["p50DeclaredLatencySeconds"] is None
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"


def test_insufficient_complete_population_withholds_percentiles():
    expected = keys(29)
    r = audit(snapshot(expected), IDENTITY, expected, [], as_of=4000)
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["p95DeclaredLatencySeconds"] is None
    assert r["withinBudgetFractionOfExpected"] == 1


def test_empty_population_no_false_positive():
    r = audit(snapshot([]), IDENTITY, [], [], as_of=4000)
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["withinBudgetFractionOfExpected"] is None
    assert r["byHorizon"] == []


def test_empty_expected_schedule_with_unexpected_issuance_requires_review():
    unexpected = [("m1", 1, 60)]
    r = audit(snapshot(unexpected), IDENTITY, [], [], as_of=4000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["expectedCount"] == 0
    assert r["p95DeclaredLatencySeconds"] is None


def test_missing_sample_capped_but_counts_complete():
    expected = keys(101)
    r = audit(snapshot([]), IDENTITY, expected, [], as_of=10000)
    assert r["missingPastDeadlineCount"] == 101
    assert len(r["missingPastDeadlineKeysFirst50"]) == 50
    assert r["truncatedMissingPastDeadlineKeys"]


@pytest.mark.parametrize("warning,min_complete", [(True, 30), (-1, 30), (31, 30),
    (15., 30), (15, True), (15, 29), (15, 5001), (15, 30.)])
def test_invalid_warning_and_minimum_fail_closed(warning, min_complete):
    with pytest.raises(ValueError):
        audit(snapshot([]), IDENTITY, [], [], as_of=4000,
              warning_seconds=warning, min_complete=min_complete)


def test_forged_source_and_invalid_abstention_rejected_by_existing_census():
    s = snapshot([])
    s["evidence"] = "LIVE_VERIFIED"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, keys(1), [], as_of=4000)
    with pytest.raises(ValueError):
        audit(snapshot([]), IDENTITY, keys(1),
              [{**abstain(keys(1)[0]), "decisionAt": True}], as_of=4000)
