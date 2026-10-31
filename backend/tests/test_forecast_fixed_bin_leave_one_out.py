"""Synthetic probability-bin concentration stress, never forward performance."""
from copy import deepcopy
import pytest
from app.forecast_fixed_bin_reliability import audit_fixed_bin_reliability


def test_leave_one_bin_out_detects_dominant_calibration_error():
    pairs = [(0.1, 0)] * 30 + [(0.5, 1)] * 30 + [(0.9, 1)] * 30
    result = audit_fixed_bin_reliability(pairs)
    assert result["status"] == "DESCRIPTIVE_ONLY"
    assert result["weightedAbsoluteCalibrationGap"] == pytest.approx(7 / 30)
    assert result["leaveOneBinOutStatus"] == "DESCRIPTIVE_ONLY"
    assert result["leaveOneBinOutBestCaseWeightedGap"] == pytest.approx(0.1)
    assert result["leaveOneBinOutWorstCaseWeightedGap"] == pytest.approx(0.3)
    assert result["maySendNotification"] is False
    assert result["mayExecutePaperOrder"] is False
    assert result["mayExecuteLiveOrder"] is False


def test_leave_one_bin_out_uses_remaining_population_not_original_denominator():
    pairs = [(0.1, 0)] * 60 + [(0.5, 1)] * 30 + [(0.9, 1)] * 30
    result = audit_fixed_bin_reliability(pairs)
    assert result["leaveOneBinOutBestCaseWeightedGap"] == pytest.approx(0.1)
    assert result["leaveOneBinOutWorstCaseWeightedGap"] == pytest.approx(0.3)


@pytest.mark.parametrize("pairs,status", [
    ([], "RELIABILITY_WITHHELD"),
    ([(0.1, 0)] * 60, "RELIABILITY_WITHHELD"),
    ([(0.1, 0)] * 30 + [(0.9, 1)] * 30, "INSUFFICIENT_REMAINING_BINS"),
    ([(0.1, 0)] * 30 + [(0.5, 1)] * 30 + [(0.9, 1)] * 29, "RELIABILITY_WITHHELD"),
])
def test_leave_one_bin_out_withheld_when_coverage_inadequate(pairs, status):
    result = audit_fixed_bin_reliability(pairs)
    assert result["leaveOneBinOutStatus"] == status
    assert result["leaveOneBinOutBestCaseWeightedGap"] is None
    assert result["leaveOneBinOutWorstCaseWeightedGap"] is None


def test_leave_one_bin_out_is_order_independent_and_does_not_mutate_input():
    pairs = [(0.1, 0)] * 30 + [(0.5, 1)] * 30 + [(0.9, 1)] * 30
    original = deepcopy(pairs)
    a = audit_fixed_bin_reliability(pairs)
    b = audit_fixed_bin_reliability(list(reversed(pairs)))
    assert pairs == original
    assert a["leaveOneBinOutStatus"] == b["leaveOneBinOutStatus"]
    for key in ("leaveOneBinOutBestCaseWeightedGap",
                "leaveOneBinOutWorstCaseWeightedGap"):
        assert a[key] == pytest.approx(b[key])
