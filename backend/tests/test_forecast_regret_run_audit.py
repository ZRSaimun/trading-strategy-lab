"""Synthetic chronological paired-loss stress, never realized market P&L."""
from copy import deepcopy
import pytest
from app.forecast_regret_run_audit import audit_chronological_regret_runs


def test_contiguous_excursion_includes_partial_recovery_but_not_favorable_prefix():
    seq = [(-.5, -3), (.2, 1), (.3, 2), (-.1, -1), (.4, 5), (-.9, -9)] * 5
    result = audit_chronological_regret_runs(seq)
    assert result["status"] == "DESCRIPTIVE_ONLY"
    assert result["maxCumulativeBrierUnderperformanceExcursion"] == pytest.approx(.8)
    assert result["maxCumulativeLogLossUnderperformanceExcursion"] == pytest.approx(7)
    assert result["longestConsecutiveBrierUnderperformance"] == 2
    assert result["longestConsecutiveLogLossUnderperformance"] == 2
    assert not result["maySendNotification"] and not result["mayExecuteLiveOrder"]


def test_all_favorable_scores_have_zero_adverse_run():
    result = audit_chronological_regret_runs([(-.2, -.1)] * 30)
    assert result["maxCumulativeBrierUnderperformanceExcursion"] == 0
    assert result["maxCumulativeLogLossUnderperformanceExcursion"] == 0
    assert result["longestConsecutiveBrierUnderperformance"] == 0


def test_long_run_cannot_be_disguised_by_low_average():
    seq = [(0.2, 0.3)] * 20 + [(-.8, -3)] * 20
    result = audit_chronological_regret_runs(seq)
    assert sum(x[0] for x in seq) < 0
    assert result["maxCumulativeBrierUnderperformanceExcursion"] == pytest.approx(4)
    assert result["longestConsecutiveBrierUnderperformance"] == 20


def test_population_gate_withholds_all_run_metrics():
    result = audit_chronological_regret_runs([(0.2, 0.1)] * 29)
    assert result["status"] == "INSUFFICIENT_DISJOINT_SCORES"
    assert result["maxCumulativeBrierUnderperformanceExcursion"] is None
    assert result["longestConsecutiveBrierUnderperformance"] is None


def test_input_immutable_and_order_matters():
    seq = [(0.5, 0.5)] * 15 + [(-0.5, -0.5)] * 15
    original = deepcopy(seq)
    a = audit_chronological_regret_runs(seq)
    assert seq == original
    assert a["maxCumulativeBrierUnderperformanceExcursion"] == pytest.approx(7.5)
    alt = audit_chronological_regret_runs([(0.5, 0.5), (-0.5, -0.5)] * 15)
    assert alt["maxCumulativeBrierUnderperformanceExcursion"] == pytest.approx(0.5)


@pytest.mark.parametrize("bad,kwargs", [
    ([(True, 0.1)] * 30, {}),
    ([(float("nan"), 0.1)] * 30, {}),
    ([(0.1, float("inf"))] * 30, {}),
    ([(0.1,)] * 30, {}),
    ([ "bad" ] * 30, {}),
    ([(1.1, 0.1)] * 30, {}),
    ([(0.1, 1001)] * 30, {}),
    ([(0.1, 10**1000)] * 30, {}),
    ([(0.1, 0.1)] * 30, {"min_scored": True}),
    ([(0.1, 0.1)] * 30, {"min_scored": 29}),
])
def test_invalid_input_rejected(bad, kwargs):
    with pytest.raises(ValueError):
        audit_chronological_regret_runs(bad, **kwargs)
