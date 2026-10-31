"""Synthetic label-perturbation sensitivity; never market or broker evidence."""
from copy import deepcopy
import pytest
from app.forecast_fixed_bin_reliability import audit_fixed_bin_reliability


def test_one_flip_bounds_cover_all_possible_directions():
    pairs = [(.2, 1)] * 15 + [(.2, 0)] * 15 + [(.8, 1)] * 15 + [(.8, 0)] * 15
    report = audit_fixed_bin_reliability(pairs)
    assert report["status"] == "DESCRIPTIVE_ONLY"
    assert report["weightedAbsoluteCalibrationGap"] == pytest.approx(.3)
    assert report["singleOutcomeFlipBestCaseWeightedGap"] == pytest.approx(.3 - 1 / 60)
    assert report["singleOutcomeFlipWorstCaseWeightedGap"] == pytest.approx(.3 + 1 / 60)
    assert not report["maySendNotification"] and not report["mayExecuteLiveOrder"]


def test_one_flip_with_one_sided_bins_can_only_improve_gap():
    pairs = [(.2, 0)] * 30 + [(.8, 1)] * 30
    report = audit_fixed_bin_reliability(pairs)
    assert report["singleOutcomeFlipBestCaseWeightedGap"] == pytest.approx(.2 - 1 / 60)
    assert report["singleOutcomeFlipWorstCaseWeightedGap"] == pytest.approx(.2 - 1 / 60)


@pytest.mark.parametrize("pairs,status", [
    ([ (.7, 1)] * 60, "LIMITED_PROBABILITY_COVERAGE"),
    ([ (.2, 1)] * 30 + [(.8, 0)] * 30 + [(.5, 1)], "INSUFFICIENT_BIN_SUPPORT"),
    ([], "LIMITED_PROBABILITY_COVERAGE"),
])
def test_one_flip_metrics_withheld_without_supported_multi_bin_population(pairs, status):
    report = audit_fixed_bin_reliability(pairs)
    assert report["status"] == status
    assert report["singleOutcomeFlipBestCaseWeightedGap"] is None
    assert report["singleOutcomeFlipWorstCaseWeightedGap"] is None


def test_one_flip_does_not_change_original_pairs_or_bin_counts():
    pairs = [(.2, 1)] * 30 + [(.8, 0)] * 30
    before = deepcopy(pairs)
    report = audit_fixed_bin_reliability(pairs)
    assert pairs == before
    assert sum(bucket["count"] for bucket in report["bins"]) == len(pairs)
    assert report["singleOutcomeFlipBestCaseWeightedGap"] <= report["singleOutcomeFlipWorstCaseWeightedGap"]
