"""Invented observations only; never a live forecast or paper-trading return."""
from copy import deepcopy
import math
import pytest

from app.forecast_temporal_calibration_audit import (
    _issued_probability_ecdf_shift, _issued_probability_shape_shift,
    _issued_utc_hour_mix,
    audit_temporal_forecast_calibration)

IDENTITY = {"instrument": "SYNTH", "provider": "FAKE", "venue": "TEST",
            "sourceId": "offline", "priceSide": "bid", "seconds": 60}


def fixture(n=160, horizon=1, p_early=.7, p_late=.7, y_early=True, y_late=True):
    events, forecasts = [], []
    for i in range(n):
        base = 60 * (i + 1)
        p = p_early if i < n // 2 else p_late
        y = y_early if i < n // 2 else y_late
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": "model",
                       "horizon": horizon, "probability": p,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": "model", "horizon": horizon,
                          "probability": p, "baseStart": base, "baseClose": 100,
                          "issuedAt": base + 60, "targetStart": base + 60 * horizon,
                          "status": "SETTLED",
                          "resolvedAt": base + 60 * (horizon + 1),
                          "outcomeUp": y})
    return {"sequence": n, "identity": IDENTITY.copy(), "maxLagSeconds": 60,
            "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def test_constant_synthetic_cohorts_report_descriptive_only():
    report = audit_temporal_forecast_calibration(fixture())
    group = report["groups"][0]
    assert group["status"] == "DESCRIPTIVE_ONLY"
    assert group["earlyNonoverlappingSettled"] >= 30
    assert group["lateNonoverlappingSettled"] >= 30
    assert group["lateBrier"] == pytest.approx(.09)
    assert group["lateBrierDelta"] == pytest.approx(0)
    assert report["forwardNetReturn"] is None and report["maximumDrawdown"] is None
    assert report["sourceAuthenticated"] is False
    assert report["mayExecuteLiveOrder"] is False


def test_deterioration_detected_without_trading_claims():
    row = audit_temporal_forecast_calibration(
        fixture(p_early=.9, p_late=.9, y_early=True, y_late=False))["groups"][0]
    assert row["descriptiveDriftFlag"] is True
    assert row["lateBrierDelta"] > .5
    assert row["status"] == "DESCRIPTIVE_BRIER_DETERIORATION_REVIEW"
    assert isinstance(row["lateBrierSkillVsFrozenEarlyClimatology"], float)


def test_frozen_early_baseline_not_fit_on_late_labels():
    a = audit_temporal_forecast_calibration(fixture(y_late=True))["groups"][0]
    b = audit_temporal_forecast_calibration(fixture(y_late=False))["groups"][0]
    assert a["lateBrierSkillVsFrozenEarlyClimatology"] != b["lateBrierSkillVsFrozenEarlyClimatology"]
    assert a["earlyBrier"] == b["earlyBrier"]


def test_small_effective_sample_withheld_for_overlapping_horizon():
    row = audit_temporal_forecast_calibration(fixture(n=160, horizon=12))["groups"][0]
    assert row["status"] == "INSUFFICIENT_NONOVERLAPPING_OUTCOMES"
    assert row["lateBrier"] is None


def test_pending_or_void_in_late_cohort_withholds_metrics():
    for status in ("PENDING", "VOID_GAP"):
        s = fixture()
        for r in s["forecasts"][100:]:
            r["status"] = status
            r["outcomeUp"] = None
            r["resolvedAt"] = None if status == "PENDING" else r["resolvedAt"]
        row = audit_temporal_forecast_calibration(s)["groups"][0]
        assert row["status"] in ("UNRESOLVED_SELECTION_RISK", "INSUFFICIENT_NONOVERLAPPING_OUTCOMES")
        assert row["lateBrier"] is None



def test_late_resolved_early_label_counts_as_boundary_missingness():
    s = fixture()
    # Last early forecast settles exactly as the late cohort starts.
    boundary = s["forecasts"][80]["issuedAt"]
    s["forecasts"][79]["resolvedAt"] = boundary
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.01)["groups"][0]
    assert row["earlyNonoverlappingSettled"] >= 30
    assert row["lateNonoverlappingSettled"] >= 30
    assert row["earlyPurgedForChronology"] == 1
    assert row["earlyUnavailableAtBoundary"] == 1
    assert row["earlyUnavailableAtBoundaryFraction"] == pytest.approx(1 / 80)
    assert row["lateUnresolvedOrVoidFraction"] == 0
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["earlyBrier"] is None and row["lateBrier"] is None
    assert row["descriptiveDriftFlag"] is None


@pytest.mark.parametrize("censored_index, expected_early, expected_late", [
    (0, 39, 40), (1, 40, 40), (80, 40, 39), (81, 40, 40),
])
def test_missing_outcome_does_not_shift_fixed_issued_sampling_census(
        censored_index, expected_early, expected_late):
    s = fixture()
    s["forecasts"][censored_index].update(
        status="PENDING", outcomeUp=None, resolvedAt=None)
    group = audit_temporal_forecast_calibration(s)["groups"][0]
    assert group["earlyNonoverlappingIssued"] == 40
    assert group["lateNonoverlappingIssued"] == 40
    assert group["earlyNonoverlappingSettled"] == expected_early
    assert group["lateNonoverlappingSettled"] == expected_late
    # The unmodified fixture already has one boundary-unavailable early
    # outcome; censoring must add exactly one more, not erase that risk.
    baseline = audit_temporal_forecast_calibration(fixture())["groups"][0]
    missing = group["earlyUnavailableAtBoundary"] + group["lateUnresolvedOrVoid"]
    baseline_missing = (baseline["earlyUnavailableAtBoundary"]
                        + baseline["lateUnresolvedOrVoid"])
    assert missing == baseline_missing + 1


def test_pending_and_post_boundary_labels_share_one_risk_budget():
    s = fixture()
    s["forecasts"][0].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    s["forecasts"][79]["resolvedAt"] = s["forecasts"][80]["issuedAt"]
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.02)["groups"][0]
    assert row["earlyPurgedForChronology"] == 1
    assert row["earlyUnresolvedOrVoid"] == 1
    assert row["earlyUnavailableAtBoundary"] == 2
    assert row["earlyUnavailableAtBoundaryFraction"] == pytest.approx(2 / 80)
    assert row["earlyNonoverlappingSettled"] >= 30
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateBrierSkillVsFrozenEarlyClimatology"] is None


def test_empty_journal_safe():
    s = fixture(0)
    result = audit_temporal_forecast_calibration(s)
    assert result["groups"] == [] and result["issuedTotal"] == 0


@pytest.mark.parametrize("bad", [
    {"min_per_window": True}, {"min_per_window": 1}, {"min_per_window": 1001},
    {"brier_deterioration": 0}, {"brier_deterioration": float("nan")},
    {"brier_deterioration": True}, {"max_unresolved_fraction": 1},
    {"max_unresolved_fraction": -1}, {"max_unresolved_fraction": True},
])
def test_invalid_settings_fail_closed(bad):
    with pytest.raises(ValueError):
        audit_temporal_forecast_calibration(fixture(), **bad)


def test_malformed_outcome_and_identity_rejected():
    for change in ("bad-evidence", "future-resolution", "early-issuance", "duplicate-base"):
        s = fixture()
        if change == "bad-evidence":
            s["evidence"] = "LIVE"
        elif change == "future-resolution":
            s["forecasts"][0]["resolvedAt"] = s["forecasts"][0]["issuedAt"]
        elif change == "early-issuance":
            s["forecasts"][0]["issuedAt"] -= 1
            s["events"][0]["receivedAt"] -= 1
        else:
            s["forecasts"][1]["baseStart"] = s["forecasts"][0]["baseStart"]
            s["forecasts"][1]["targetStart"] = s["forecasts"][0]["targetStart"]
            s["events"][1]["baseStart"] = s["events"][0]["baseStart"]
        with pytest.raises(ValueError):
            audit_temporal_forecast_calibration(s)


def test_does_not_mutate_journal():
    s = fixture()
    before = deepcopy(s)
    audit_temporal_forecast_calibration(s)
    assert s == before


@pytest.mark.parametrize("cohort, indices", [
    ("early", (0, 2, 4)), ("late", (80, 82, 84)),
])
def test_selected_census_missingness_cannot_hide_in_issued_denominator(cohort, indices):
    s = fixture()
    for i in indices:
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["earlyNonoverlappingIssued"] == 40
    assert row["lateNonoverlappingIssued"] == 40
    if cohort == "early":
        assert row["earlyUnavailableAtBoundaryFraction"] == pytest.approx(.05)
        assert row["earlyCensusUnavailableAtBoundary"] == 3
        assert row["earlyCensusUnavailableAtBoundaryFraction"] == pytest.approx(.075)
    else:
        assert row["lateUnresolvedOrVoidFraction"] == pytest.approx(3 / 80)
        assert row["lateCensusUnresolvedOrVoid"] == 3
        assert row["lateCensusUnresolvedOrVoidFraction"] == pytest.approx(.075)
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["earlyBrier"] is None and row["lateBrier"] is None


@pytest.mark.parametrize("indices", [(1, 3, 5), (81, 83, 85)])
def test_unselected_missingness_still_counted_but_does_not_shift_census(indices):
    s = fixture()
    for i in indices:
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["earlyCensusUnavailableAtBoundary"] == 0
    assert row["lateCensusUnresolvedOrVoid"] == 0
    assert row["earlyNonoverlappingIssued"] == 40
    assert row["lateNonoverlappingIssued"] == 40
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["lateBrier"] is not None


def test_selected_early_post_boundary_labels_count_in_census_risk():
    s = fixture()
    boundary = s["forecasts"][80]["issuedAt"]
    for i in (72, 74, 76):
        s["forecasts"][i]["resolvedAt"] = boundary
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["earlyUnavailableAtBoundaryFraction"] == pytest.approx(.05)
    assert row["earlyCensusUnavailableAtBoundary"] == 3
    assert row["earlyCensusUnavailableAtBoundaryFraction"] == pytest.approx(.075)
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateBrierSkillVsFrozenEarlyClimatology"] is None


def test_temporal_ece_detects_compensating_bin_miscalibration():
    s = fixture()
    # Fixed selected late census is every other row (80, 82, ...).
    # Half the selected predictions are 0.2 but all resolve UP;
    # the other half are 0.8 but all resolve DOWN. Overall means
    # cancel to 0.5, hiding severe within-bin miscalibration.
    for i in range(80, 160):
        low_probability = ((i - 80) // 2) % 2 == 0
        p = 0.2 if low_probability else 0.8
        s["forecasts"][i]["probability"] = p
        s["forecasts"][i]["outcomeUp"] = low_probability
        s["events"][i]["probability"] = p
    group = audit_temporal_forecast_calibration(s)["groups"][0]
    assert group["status"] == "DESCRIPTIVE_BRIER_DETERIORATION_REVIEW"
    assert group["lateNonoverlappingSettled"] == 40
    assert group["lateMeanProbability"] == pytest.approx(0.5)
    assert group["lateObservedUpRate"] == pytest.approx(0.5)
    assert group["lateAbsoluteCalibrationGap"] == pytest.approx(0)
    assert group["lateExpectedCalibrationError10"] == pytest.approx(0.8)


def test_temporal_ece_is_withheld_with_other_scores_on_selection_risk():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    group = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=0.05)["groups"][0]
    assert group["status"] == "UNRESOLVED_SELECTION_RISK"
    assert group["lateExpectedCalibrationError10"] is None
    assert group["lateAbsoluteCalibrationGap"] is None


def test_temporal_ece_bin_population_is_reproducible():
    s = fixture()
    for i in range(80, 160):
        low = ((i - 80) // 2) % 2 == 0
        p = 0.2 if low else 0.8
        s["forecasts"][i]["probability"] = p
        s["forecasts"][i]["outcomeUp"] = low
        s["events"][i]["probability"] = p
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    bins = row["lateEceBins10"]
    assert len(bins) == 10
    assert [b["bin"] for b in bins] == list(range(10))
    assert [b["count"] for b in bins] == [0, 0, 20, 0, 0, 0, 0, 0, 20, 0]
    assert sum(b["count"] for b in bins) == row["lateNonoverlappingSettled"]
    reconstructed = sum(
        b["count"] * abs(b["meanProbability"] - b["observedUpRate"])
        for b in bins if b["count"]
    ) / row["lateNonoverlappingSettled"]
    assert reconstructed == pytest.approx(row["lateExpectedCalibrationError10"])
    assert bins[2]["observedUpRate"] == 1.0
    assert bins[8]["observedUpRate"] == 0.0
    assert bins[0]["meanProbability"] is None
    assert bins[0]["observedUpRate"] is None


def test_temporal_ece_bins_withheld_with_selection_risk():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateExpectedCalibrationError10"] is None
    assert row["lateEceBins10"] is None


def test_temporal_ece_bins_do_not_invent_rates_for_empty_bins():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    bins = row["lateEceBins10"]
    assert sum(b["count"] for b in bins) == row["lateNonoverlappingSettled"]
    assert sum(b["count"] > 0 for b in bins) == 1
    assert all(b["meanProbability"] is None and b["observedUpRate"] is None
               for b in bins if b["count"] == 0)


def test_temporal_ece_bin_wilson_intervals_flag_sparse_support():
    s = fixture()
    for i in range(80, 160):
        low = ((i - 80) // 2) % 2 == 0
        p = .2 if low else .8
        s["forecasts"][i]["probability"] = p
        s["forecasts"][i]["outcomeUp"] = low
        s["events"][i]["probability"] = p
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    bins = row["lateEceBins10"]
    assert row["lateEceOccupiedBinsUnder30"] == 2
    assert row["lateEceMinOccupiedBinCount"] == 20
    for i in (2, 8):
        assert bins[i]["count"] == 20
        assert bins[i]["lowSupportUnder30"] is True
        lo, hi = bins[i]["observedUpWilson95Descriptive"]
        assert 0 <= lo <= hi <= 1
        assert hi - lo == pytest.approx(.161125, abs=.0001)
    assert bins[2]["observedUpWilson95Descriptive"][1] == pytest.approx(1)
    assert bins[8]["observedUpWilson95Descriptive"][0] == pytest.approx(0)
    assert bins[0]["observedUpWilson95Descriptive"] is None
    assert bins[0]["lowSupportUnder30"] is None


def test_temporal_ece_full_single_bin_has_reported_support():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateEceOccupiedBinsUnder30"] == 0
    assert row["lateEceMinOccupiedBinCount"] == 40
    occupied = [b for b in row["lateEceBins10"] if b["count"]]
    assert len(occupied) == 1
    assert occupied[0]["lowSupportUnder30"] is False
    assert occupied[0]["observedUpWilson95Descriptive"][1] == pytest.approx(1)


def test_temporal_ece_bin_uncertainty_withheld_on_selection_risk():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateEceBins10"] is None
    assert row["lateEceOccupiedBinsUnder30"] is None
    assert row["lateEceMinOccupiedBinCount"] is None


def test_temporal_log_loss_reports_proper_score_without_profit_claims():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["earlyLogLoss"] == pytest.approx(-math.log(.7))
    assert row["lateLogLoss"] == pytest.approx(-math.log(.7))
    assert row["lateLogLossDelta"] == pytest.approx(0)
    assert math.isfinite(row["lateLogLossSkillVsFrozenEarlyClimatology"])


def test_temporal_log_loss_detects_confidently_wrong_late_probabilities():
    row = audit_temporal_forecast_calibration(
        fixture(p_early=.9, p_late=.9, y_early=True, y_late=False))["groups"][0]
    assert row["earlyLogLoss"] == pytest.approx(-math.log(.9))
    assert row["lateLogLoss"] == pytest.approx(-math.log(.1))
    assert row["lateLogLossDelta"] > 2
    assert row["status"] == "DESCRIPTIVE_BRIER_DETERIORATION_REVIEW"


@pytest.mark.parametrize("p_late,y_late", [
    (1e-300, False), (1 - 2**-52, False),
])
def test_temporal_log_loss_is_finite_at_extreme_interior_probabilities(p_late, y_late):
    row = audit_temporal_forecast_calibration(
        fixture(p_late=p_late, y_late=y_late))["groups"][0]
    assert math.isfinite(row["lateLogLoss"])
    assert math.isfinite(row["lateLogLossSkillVsFrozenEarlyClimatology"])
    assert row["lateLogLoss"] >= 0


def test_temporal_log_loss_withheld_for_selected_missing_outcomes():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    for key in ("earlyLogLoss", "lateLogLoss", "lateLogLossDelta",
                "lateLogLossSkillVsFrozenEarlyClimatology"):
        assert row[key] is None


def test_temporal_log_loss_early_training_does_not_learn_late_outcomes():
    a = audit_temporal_forecast_calibration(fixture(y_late=True))["groups"][0]
    b = audit_temporal_forecast_calibration(fixture(y_late=False))["groups"][0]
    assert a["earlyLogLoss"] == b["earlyLogLoss"]
    assert a["lateLogLoss"] != b["lateLogLoss"]



@pytest.mark.parametrize("cutoff", [True, False, -1, 1.5, "9660", 2**53])
def test_declared_evaluation_cutoff_rejects_invalid_values(cutoff):
    with pytest.raises(ValueError, match="Invalid declared evaluation cutoff"):
        audit_temporal_forecast_calibration(fixture(), evaluation_as_of=cutoff)


def test_declared_evaluation_cutoff_rejects_future_issued_forecasts():
    s = fixture()
    last_issued = max(r["issuedAt"] for r in s["forecasts"])
    with pytest.raises(ValueError, match="predates issued forecasts"):
        audit_temporal_forecast_calibration(s, evaluation_as_of=last_issued - 1)


def test_declared_as_of_cutoff_excludes_future_settlements_from_selected_census():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    for i in (80, 82, 84):
        s["forecasts"][i]["resolvedAt"] = cutoff + 100
    before = deepcopy(s)
    result = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff, max_unresolved_fraction=.05)
    row = result["groups"][0]
    assert result["evaluationAsOfDeclared"] == cutoff
    assert result["evaluationCutoffAuthenticated"] is False
    assert row["lateSettledAfterDeclaredAsOf"] == 4  # plus final unselected row
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 3
    assert row["lateUnavailableAtDeclaredAsOfFraction"] == pytest.approx(.05)
    assert row["lateCensusUnavailableAtDeclaredAsOfFraction"] == pytest.approx(.075)
    assert row["lateUnresolvedOrVoid"] == 0
    assert row["lateNonoverlappingSettled"] == 37
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    for field in ("lateBrier", "lateLogLoss", "lateEceBins10",
                  "lateLogLossSkillVsFrozenEarlyClimatology"):
        assert row[field] is None
    assert s == before


def test_unselected_post_cutoff_labels_do_not_shift_fixed_census():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    for i in (81, 83, 85):
        s["forecasts"][i]["resolvedAt"] = cutoff + 100
    baseline = audit_temporal_forecast_calibration(s)["groups"][0]
    row = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff, max_unresolved_fraction=.05)["groups"][0]
    assert row["lateSettledAfterDeclaredAsOf"] == 4
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 0
    assert row["lateNonoverlappingSettled"] == 40
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["lateLogLoss"] == baseline["lateLogLoss"]
    assert row["lateBrier"] == baseline["lateBrier"]


def test_declared_cutoff_includes_exact_boundary_resolution():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    s["forecasts"][80]["resolvedAt"] = cutoff
    row = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff)["groups"][0]
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 0
    assert row["lateNonoverlappingSettled"] == 40
    assert row["lateBrier"] is not None


def test_declared_cutoff_after_all_settlements_preserves_retrospective_scores():
    s = fixture()
    cutoff = max(r["resolvedAt"] for r in s["forecasts"])
    baseline = audit_temporal_forecast_calibration(s)["groups"][0]
    report = audit_temporal_forecast_calibration(s, evaluation_as_of=cutoff)
    row = report["groups"][0]
    assert row["lateSettledAfterDeclaredAsOf"] == 0
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 0
    assert row["lateBrier"] == baseline["lateBrier"]
    assert row["lateLogLoss"] == baseline["lateLogLoss"]
    assert report["maySendNotification"] is False
    assert report["mayExecuteLiveOrder"] is False


def test_temporal_high_confidence_tail_counts_confident_wrong_up_calls():
    row = audit_temporal_forecast_calibration(
        fixture(p_late=.95, y_late=False))["groups"][0]
    assert row["lateHighConfidenceCount"] == 40
    assert row["lateHighConfidenceFractionOfSettled"] == pytest.approx(1)
    assert row["lateHighConfidenceWrong"] == 40
    assert row["lateHighConfidenceWrongFraction"] == pytest.approx(1)
    assert row["lateHighConfidenceWrongWilson95Descriptive"][1] == pytest.approx(1)
    assert row["lateHighConfidenceLowSupportUnder30"] is False


def test_temporal_high_confidence_tail_counts_correct_down_calls():
    row = audit_temporal_forecast_calibration(
        fixture(p_late=.05, y_late=False))["groups"][0]
    assert row["lateHighConfidenceCount"] == 40
    assert row["lateHighConfidenceWrong"] == 0
    assert row["lateHighConfidenceWrongFraction"] == pytest.approx(0)
    assert row["lateHighConfidenceWrongWilson95Descriptive"][0] == pytest.approx(0)


def test_temporal_high_confidence_empty_tail_does_not_invent_error_rate():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateHighConfidenceCount"] == 0
    assert row["lateHighConfidenceFractionOfSettled"] == pytest.approx(0)
    assert row["lateHighConfidenceWrong"] == 0
    assert row["lateHighConfidenceWrongFraction"] is None
    assert row["lateHighConfidenceWrongWilson95Descriptive"] is None
    assert row["lateHighConfidenceLowSupportUnder30"] is None


def test_temporal_high_confidence_tail_uses_fixed_selected_census():
    s = fixture()
    for i in range(80, 160):
        p = .9 if i % 4 < 2 else .1
        s["forecasts"][i]["probability"] = p
        s["events"][i]["probability"] = p
        s["forecasts"][i]["outcomeUp"] = False
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateHighConfidenceCount"] == 40
    assert row["lateHighConfidenceWrong"] == 20
    assert row["lateHighConfidenceWrongFraction"] == pytest.approx(.5)


def test_temporal_high_confidence_diagnostics_withheld_with_selection_risk():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    for key in ("lateHighConfidenceCount", "lateHighConfidenceFractionOfSettled",
                "lateHighConfidenceWrong", "lateHighConfidenceWrongFraction",
                "lateHighConfidenceWrongWilson95Descriptive",
                "lateHighConfidenceLowSupportUnder30"):
        assert row[key] is None


def test_late_brier_binary_bounds_collapse_when_selected_census_fully_settled():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateBrierBestCaseAllIssuedCensus"] == pytest.approx(row["lateBrier"])
    assert row["lateBrierWorstCaseAllIssuedCensus"] == pytest.approx(row["lateBrier"])


def test_late_brier_binary_bounds_cover_one_pending_selected_outcome():
    s = fixture()
    s["forecasts"][80].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    original = deepcopy(s)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["lateNonoverlappingIssued"] == 40
    assert row["lateNonoverlappingSettled"] == 39
    assert row["lateBrier"] == pytest.approx(.09)
    assert row["lateBrierBestCaseAllIssuedCensus"] == pytest.approx(.09)
    assert row["lateBrierWorstCaseAllIssuedCensus"] == pytest.approx(.10)
    assert s == original


def test_late_brier_binary_bounds_include_cutoff_unavailable_labels():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    s["forecasts"][80]["resolvedAt"] = cutoff + 100
    row = audit_temporal_forecast_calibration(s, evaluation_as_of=cutoff)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 1
    assert row["lateBrierBestCaseAllIssuedCensus"] == pytest.approx(.09)
    assert row["lateBrierWorstCaseAllIssuedCensus"] == pytest.approx(.10)
    assert row["lateBrier"] == pytest.approx(.09)


def test_late_brier_binary_bounds_respond_to_confident_wrong_predictions():
    s = fixture(p_late=.95, y_late=False)
    s["forecasts"][80].update(status="VOID_GAP", outcomeUp=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_BRIER_DETERIORATION_REVIEW"
    assert row["lateBrier"] == pytest.approx(.9025)
    assert row["lateBrierBestCaseAllIssuedCensus"] == pytest.approx(
        (39 * .9025 + .0025) / 40)
    assert row["lateBrierWorstCaseAllIssuedCensus"] == pytest.approx(.9025)


def test_late_brier_binary_bounds_withheld_when_selected_missingness_exceeds_gate():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateBrierBestCaseAllIssuedCensus"] is None
    assert row["lateBrierWorstCaseAllIssuedCensus"] is None


def test_unselected_missing_outcome_does_not_change_fixed_census_bounds():
    s = fixture()
    s["forecasts"][81].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateBrierBestCaseAllIssuedCensus"] == pytest.approx(.09)
    assert row["lateBrierWorstCaseAllIssuedCensus"] == pytest.approx(.09)


def test_binned_brier_components_constant_cohort():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateBrierBinned10Reliability"] == pytest.approx(.09)
    assert row["lateBrierBinned10Resolution"] == pytest.approx(0)
    assert row["lateBrierBinned10Uncertainty"] == pytest.approx(0)
    assert row["lateBrierBinned10Residual"] == pytest.approx(0)
    assert row["lateBrier"] == pytest.approx(
        row["lateBrierBinned10Reliability"] -
        row["lateBrierBinned10Resolution"] +
        row["lateBrierBinned10Uncertainty"] +
        row["lateBrierBinned10Residual"])


def test_binned_brier_components_separate_reliability_and_resolution():
    s = fixture()
    for i in range(80, 160):
        low = ((i - 80) // 2) % 2 == 0
        s["forecasts"][i]["probability"] = .2 if low else .8
        s["forecasts"][i]["outcomeUp"] = low
        s["events"][i]["probability"] = .2 if low else .8
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateBrier"] == pytest.approx(.64)
    assert row["lateBrierBinned10Reliability"] == pytest.approx(.64)
    assert row["lateBrierBinned10Resolution"] == pytest.approx(.25)
    assert row["lateBrierBinned10Uncertainty"] == pytest.approx(.25)
    assert row["lateBrierBinned10Residual"] == pytest.approx(0)


@pytest.mark.parametrize("correlated,expected_residual", [
    (None, .0016), (True, -.0384),
])
def test_binned_brier_components_expose_within_bin_discrepancy(
        correlated, expected_residual):
    s = fixture()
    for i in range(80, 160):
        low = ((i - 80) // 2) % 2 == 0
        p = .21 if low else .29
        s["forecasts"][i]["probability"] = p
        s["forecasts"][i]["outcomeUp"] = not low if correlated else True
        s["events"][i]["probability"] = p
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateBrierBinned10Residual"] == pytest.approx(expected_residual)
    assert row["lateBrier"] == pytest.approx(
        row["lateBrierBinned10Reliability"] -
        row["lateBrierBinned10Resolution"] +
        row["lateBrierBinned10Uncertainty"] +
        row["lateBrierBinned10Residual"])


def test_binned_brier_components_withheld_under_missingness_gate():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    report = audit_temporal_forecast_calibration(s, max_unresolved_fraction=.05)
    row = report["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    for key in ("lateBrierBinned10Reliability", "lateBrierBinned10Resolution",
                "lateBrierBinned10Uncertainty", "lateBrierBinned10Residual"):
        assert row[key] is None
    assert report["maySendNotification"] is False
    assert report["mayExecutePaperOrder"] is False
    assert report["mayExecuteLiveOrder"] is False


def test_late_log_loss_bounds_collapse_when_fixed_census_fully_settled():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateLogLossBestCaseAllIssuedCensus"] == pytest.approx(row["lateLogLoss"])
    assert row["lateLogLossWorstCaseAllIssuedCensus"] == pytest.approx(row["lateLogLoss"])


def test_late_log_loss_bounds_cover_one_pending_selected_outcome_without_imputation():
    s = fixture()
    s["forecasts"][80].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    original = deepcopy(s)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["lateNonoverlappingIssued"] == 40
    assert row["lateNonoverlappingSettled"] == 39
    assert row["lateLogLossBestCaseAllIssuedCensus"] == pytest.approx(-math.log(.7))
    assert row["lateLogLossWorstCaseAllIssuedCensus"] == pytest.approx(
        (39 * -math.log(.7) - math.log(.3)) / 40)
    assert s == original


def test_late_log_loss_bounds_respect_declared_as_of_cutoff():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    s["forecasts"][80]["resolvedAt"] = cutoff + 100
    row = audit_temporal_forecast_calibration(s, evaluation_as_of=cutoff)["groups"][0]
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 1
    assert row["lateLogLossBestCaseAllIssuedCensus"] == pytest.approx(-math.log(.7))
    assert row["lateLogLossWorstCaseAllIssuedCensus"] == pytest.approx(
        (39 * -math.log(.7) - math.log(.3)) / 40)


def test_late_log_loss_bounds_remain_finite_for_extreme_interior_probabilities():
    s = fixture(p_late=1e-300, y_late=False)
    s["forecasts"][80].update(status="VOID_GAP", outcomeUp=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert math.isfinite(row["lateLogLossBestCaseAllIssuedCensus"])
    assert math.isfinite(row["lateLogLossWorstCaseAllIssuedCensus"])
    assert row["lateLogLossBestCaseAllIssuedCensus"] == pytest.approx(
        row["lateLogLoss"], rel=1e-12, abs=0)
    assert row["lateLogLossWorstCaseAllIssuedCensus"] > 17


def test_late_log_loss_bounds_withheld_under_selected_missingness_gate():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateLogLossBestCaseAllIssuedCensus"] is None
    assert row["lateLogLossWorstCaseAllIssuedCensus"] is None


def test_unselected_missing_outcome_does_not_change_fixed_log_loss_bounds():
    s = fixture()
    s["forecasts"][81].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateLogLossBestCaseAllIssuedCensus"] == pytest.approx(-math.log(.7))
    assert row["lateLogLossWorstCaseAllIssuedCensus"] == pytest.approx(-math.log(.7))


def test_log_loss_tail_constant_selected_census_has_exact_concentration():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    n = row["lateNonoverlappingSettled"]
    loss = -math.log(.7)
    assert row["lateLogLossWorstSingle"] == pytest.approx(loss)
    assert row["lateLogLossP95NearestRank"] == pytest.approx(loss)
    assert row["lateLogLossTopDecileShare"] == pytest.approx(math.ceil(n / 10) / n)
    assert row["lateWorstSingleLogLossRegretVsFrozenEarlyClimatology"] > 0


def test_log_loss_tail_exposes_one_confidently_wrong_selected_outcome():
    s = fixture(p_late=.99)
    s["forecasts"][80]["outcomeUp"] = False
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    n = row["lateNonoverlappingSettled"]
    good, bad = -math.log(.99), -math.log1p(-.99)
    top = math.ceil(n / 10)
    assert row["lateLogLossWorstSingle"] == pytest.approx(bad)
    assert row["lateLogLossP95NearestRank"] == pytest.approx(good)
    assert row["lateLogLossTopDecileShare"] == pytest.approx(
        (bad + (top - 1) * good) / (bad + (n - 1) * good))


def test_log_loss_tail_signed_worst_regret_can_be_negative():
    s = fixture(p_early=.5, p_late=.99)
    for i in range(0, 80, 2):
        s["forecasts"][i]["outcomeUp"] = False
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["lateWorstSingleLogLossRegretVsFrozenEarlyClimatology"] < 0


def test_log_loss_tail_withheld_on_concentrated_selected_missingness():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    for field in ("lateLogLossWorstSingle", "lateLogLossP95NearestRank",
                  "lateLogLossTopDecileShare",
                  "lateWorstSingleLogLossRegretVsFrozenEarlyClimatology"):
        assert row[field] is None


def test_log_loss_tail_unselected_outcome_cannot_shift_fixed_census():
    s = fixture()
    a = audit_temporal_forecast_calibration(s)["groups"][0]
    s["forecasts"][81]["outcomeUp"] = False
    b = audit_temporal_forecast_calibration(s)["groups"][0]
    for field in ("lateLogLossWorstSingle", "lateLogLossP95NearestRank",
                  "lateLogLossTopDecileShare",
                  "lateWorstSingleLogLossRegretVsFrozenEarlyClimatology"):
        assert a[field] == pytest.approx(b[field])


def test_settlement_lag_zero_on_synthetic_on_time_target_receipts():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateSettlementLagP95Seconds"] == 0
    assert row["lateSettlementLagMaxSeconds"] == 0
    assert row["lateSettlementLagOverOneCandleFraction"] == 0


def test_settlement_lag_uses_fixed_late_census_and_nearest_rank():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i]["resolvedAt"] += 120
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateNonoverlappingSettled"] == 40
    assert row["lateSettlementLagP95Seconds"] == 120
    assert row["lateSettlementLagMaxSeconds"] == 120
    assert row["lateSettlementLagOverOneCandleFraction"] == pytest.approx(3 / 40)


def test_settlement_lag_respects_declared_as_of_excluded_receipt():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    s["forecasts"][80]["resolvedAt"] = cutoff + 120
    group = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff)["groups"][0]
    assert group["lateCensusSettledAfterDeclaredAsOf"] == 1
    assert group["lateNonoverlappingSettled"] == 39
    assert group["lateSettlementLagP95Seconds"] == 0
    assert group["lateSettlementLagMaxSeconds"] == 0


def test_settlement_lag_withheld_when_selected_missingness_exceeds_gate():
    s = fixture()
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    group = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert group["status"] == "UNRESOLVED_SELECTION_RISK"
    for field in ("lateSettlementLagP95Seconds", "lateSettlementLagMaxSeconds",
                  "lateSettlementLagOverOneCandleFraction"):
        assert group[field] is None


def test_settlement_lag_ignores_unselected_forecast_receipt_delay():
    s = fixture()
    a = audit_temporal_forecast_calibration(s)["groups"][0]
    s["forecasts"][81]["resolvedAt"] += 3600
    b = audit_temporal_forecast_calibration(s)["groups"][0]
    for field in ("lateSettlementLagP95Seconds", "lateSettlementLagMaxSeconds",
                  "lateSettlementLagOverOneCandleFraction"):
        assert a[field] == b[field]


def test_issuance_lag_full_late_issued_census_and_nearest_rank_p95():
    s = fixture()
    for i in range(155, 160):
        s["forecasts"][i]["issuedAt"] += 31
        s["events"][i]["receivedAt"] += 31
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateIssuanceLagCensusCount"] == 80
    assert row["lateIssuanceLagP95Seconds"] == 31
    assert row["lateIssuanceLagMaxSeconds"] == 31
    assert row["lateIssuanceLagOverHalfCandleFraction"] == pytest.approx(5 / 80)
    assert row["lateBrier"] is not None


def test_issuance_lag_strict_half_candle_boundary():
    s = fixture()
    s["forecasts"][159]["issuedAt"] += 30
    s["events"][159]["receivedAt"] += 30
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateIssuanceLagMaxSeconds"] == 30
    assert row["lateIssuanceLagOverHalfCandleFraction"] == 0


def test_issuance_lag_not_selected_by_outcome_or_as_of_cutoff():
    s = fixture()
    s["forecasts"][159]["issuedAt"] += 31
    s["events"][159]["receivedAt"] += 31
    original = audit_temporal_forecast_calibration(s)["groups"][0]
    for i in range(100, 160):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    withheld = audit_temporal_forecast_calibration(s)["groups"][0]
    for field in ("lateIssuanceLagCensusCount", "lateIssuanceLagP95Seconds",
                  "lateIssuanceLagMaxSeconds",
                  "lateIssuanceLagOverHalfCandleFraction"):
        assert original[field] == withheld[field]
    assert withheld["lateBrier"] is None
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    as_of = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff)["groups"][0]
    assert as_of["lateIssuanceLagMaxSeconds"] == 31


def test_issuance_lag_remains_descriptive_when_horizon_scores_withheld():
    s = fixture(horizon=12)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "INSUFFICIENT_NONOVERLAPPING_OUTCOMES"
    assert row["lateBrier"] is None
    assert row["lateIssuanceLagCensusCount"] == 80
    assert row["lateIssuanceLagP95Seconds"] == 0
    assert row["lateIssuanceLagOverHalfCandleFraction"] == 0


def test_all_issued_confidence_census_is_outcome_independent():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateIssuedHighConfidenceCount"] == 0
    assert row["lateIssuedHighConfidenceFraction"] == 0
    assert row["lateIssuedMeanProbability"] == pytest.approx(.7)


def test_all_issued_confidence_census_includes_unselected_extreme_probabilities():
    s = fixture()
    # Odd-numbered late forecasts are omitted from the nonoverlapping scoring
    # sample but must remain visible in the issuance probability population.
    for i in range(80, 160):
        p = .1 if i % 4 == 0 else .9 if i % 4 == 1 else .7
        s["forecasts"][i]["probability"] = p
        s["events"][i]["probability"] = p
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateIssuedHighConfidenceCount"] == 40
    assert row["lateIssuedHighConfidenceFraction"] == pytest.approx(.5)
    assert row["lateIssuedMeanProbability"] == pytest.approx(.6)
    assert row["lateIssuanceLagCensusCount"] == 80


def test_all_issued_confidence_remains_visible_when_outcomes_are_withheld():
    s = fixture(p_late=.95)
    for i in (80, 82, 84):
        s["forecasts"][i].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(
        s, max_unresolved_fraction=.05)["groups"][0]
    assert row["status"] == "UNRESOLVED_SELECTION_RISK"
    assert row["lateHighConfidenceCount"] is None
    assert row["lateIssuedHighConfidenceCount"] == 80
    assert row["lateIssuedHighConfidenceFraction"] == 1
    assert row["lateIssuedMeanProbability"] == pytest.approx(.95)


def test_issued_high_confidence_delay_empty_tail_has_null_rate():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleCount"] == 0
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleFraction"] is None
    assert row["lateIssuedOtherDelayedOverHalfCandleFraction"] == 0


def test_issued_high_confidence_delay_cross_tab_uses_all_issued_rows():
    s = fixture()
    for i, p, lag in ((80, .9, 31), (81, .1, 30),
                      (82, .9, 32), (83, .7, 31)):
        s["forecasts"][i]["probability"] = p
        s["events"][i]["probability"] = p
        s["forecasts"][i]["issuedAt"] += lag
        s["events"][i]["receivedAt"] += lag
    # Include one selected pending and one overlap-excluded high-confidence
    # forecast; neither can disappear from this outcome-independent census.
    s["forecasts"][82].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateIssuedHighConfidenceCount"] == 3
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleCount"] == 2
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleFraction"] == pytest.approx(2 / 3)
    assert row["lateIssuedOtherDelayedOverHalfCandleFraction"] == pytest.approx(1 / 77)


def test_issued_high_confidence_delay_half_candle_is_strict():
    s = fixture(p_late=.95)
    s["forecasts"][159]["issuedAt"] += 30
    s["events"][159]["receivedAt"] += 30
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleCount"] == 0
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleFraction"] == 0
    assert row["lateIssuedOtherDelayedOverHalfCandleFraction"] is None


def test_issued_high_confidence_delay_visible_when_scores_withheld():
    s = fixture(p_late=.95, horizon=12)
    s["forecasts"][159]["issuedAt"] += 31
    s["events"][159]["receivedAt"] += 31
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    assert row["status"] == "INSUFFICIENT_NONOVERLAPPING_OUTCOMES"
    assert row["lateBrier"] is None
    assert row["lateIssuedHighConfidenceCount"] == 80
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleCount"] == 1
    assert row["lateIssuedHighConfidenceDelayedOverHalfCandleFraction"] == pytest.approx(1 / 80)
    assert row["lateIssuedOtherDelayedOverHalfCandleFraction"] is None


def test_outcome_availability_bins_use_fixed_nonoverlapping_issued_census():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    bins = row["lateCensusOutcomeAvailabilityBins10"]
    assert len(bins) == 10
    assert sum(b["issued"] for b in bins) == row["lateNonoverlappingIssued"] == 40
    assert bins[7] == {"bin": 7, "issued": 40, "eligibleSettled": 40,
                       "unavailable": 0, "unavailableFraction": 0,
                       "lowSupportUnder30": False}
    assert bins[0]["issued"] == 0
    assert bins[0]["unavailableFraction"] is None
    assert bins[0]["lowSupportUnder30"] is None


def test_outcome_availability_bins_do_not_replace_missing_selected_with_neighbor():
    s = fixture()
    s["forecasts"][80].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    s["forecasts"][81].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    b = row["lateCensusOutcomeAvailabilityBins10"][7]
    assert b["issued"] == 40
    assert b["eligibleSettled"] == 39
    assert b["unavailable"] == 1
    assert b["unavailableFraction"] == pytest.approx(1 / 40)
    # The unselected index 81 cannot shift the precommitted sampling census.
    s["forecasts"][81].update(status="SETTLED", resolvedAt=5040, outcomeUp=True)
    again = audit_temporal_forecast_calibration(s)["groups"][0]
    assert again["lateCensusOutcomeAvailabilityBins10"] == row["lateCensusOutcomeAvailabilityBins10"]


def test_outcome_availability_bins_respect_declared_as_of_settlement_cutoff():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    s["forecasts"][80]["resolvedAt"] = cutoff + 120
    row = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff)["groups"][0]
    b = row["lateCensusOutcomeAvailabilityBins10"][7]
    assert b["issued"] == 40
    assert b["eligibleSettled"] == 39
    assert b["unavailable"] == 1
    assert row["lateCensusSettledAfterDeclaredAsOf"] == 1


def test_outcome_availability_bins_remain_when_scoring_insufficient():
    row = audit_temporal_forecast_calibration(fixture(horizon=12))["groups"][0]
    assert row["status"] == "INSUFFICIENT_NONOVERLAPPING_OUTCOMES"
    assert row["lateBrier"] is None
    b = row["lateCensusOutcomeAvailabilityBins10"][7]
    assert b["issued"] == row["lateNonoverlappingIssued"]
    assert b["eligibleSettled"] == b["issued"]
    assert b["lowSupportUnder30"] is True


def test_outcome_availability_bins_include_probability_boundaries():
    s = fixture()
    for index, p in ((80, .10), (82, .90)):
        s["forecasts"][index]["probability"] = p
        s["events"][index]["probability"] = p
    bins = audit_temporal_forecast_calibration(s)["groups"][0][
        "lateCensusOutcomeAvailabilityBins10"]
    assert bins[1]["issued"] == 1
    assert bins[9]["issued"] == 1
    assert bins[7]["issued"] == 38
    assert sum(b["unavailable"] for b in bins) == 0


def test_issued_probability_shift_identical_cohorts_is_zero():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["earlyIssuedProbabilityBins10"] == row["lateIssuedProbabilityBins10"]
    assert row["earlyIssuedProbabilityBins10"][7] == 80
    assert row["issuedProbabilityJensenShannonBits10"] == pytest.approx(0)
    assert row["issuedProbabilityShiftLowSupportUnder30"] is False


def test_issued_probability_shift_disjoint_cohorts_is_one_bit():
    row = audit_temporal_forecast_calibration(
        fixture(p_early=.10, p_late=.90))["groups"][0]
    assert row["earlyIssuedProbabilityBins10"][1] == 80
    assert row["lateIssuedProbabilityBins10"][9] == 80
    assert row["issuedProbabilityJensenShannonBits10"] == pytest.approx(1)
    assert row["lateBrier"] is not None


def test_issued_probability_shift_does_not_select_on_settlement_or_cutoff():
    s = fixture(p_early=.10, p_late=.90)
    before = audit_temporal_forecast_calibration(s)["groups"][0]
    for r in s["forecasts"][80:]:
        r.update(status="PENDING", outcomeUp=None, resolvedAt=None)
    after = audit_temporal_forecast_calibration(s)["groups"][0]
    for key in ("earlyIssuedProbabilityBins10", "lateIssuedProbabilityBins10",
                "issuedProbabilityJensenShannonBits10",
                "issuedProbabilityShiftLowSupportUnder30"):
        assert after[key] == before[key]
    assert after["lateBrier"] is None
    assert after["status"] == "INSUFFICIENT_NONOVERLAPPING_OUTCOMES"


def test_issued_probability_shift_small_cohorts_flag_low_support():
    row = audit_temporal_forecast_calibration(
        fixture(n=2, p_early=.10, p_late=.90))["groups"][0]
    assert sum(row["earlyIssuedProbabilityBins10"]) == 1
    assert sum(row["lateIssuedProbabilityBins10"]) == 1
    assert row["issuedProbabilityJensenShannonBits10"] == pytest.approx(1)
    assert row["issuedProbabilityShiftLowSupportUnder30"] is True
    assert row["lateBrier"] is None


def test_issued_unbinned_shift_identical_distributions_zero():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["issuedProbabilityWasserstein1"] == pytest.approx(0)
    assert row["issuedProbabilityKsGap"] == pytest.approx(0)


def test_issued_unbinned_shift_disjoint_probabilities_exact_distance():
    row = audit_temporal_forecast_calibration(
        fixture(p_early=.10, p_late=.90))["groups"][0]
    assert row["issuedProbabilityWasserstein1"] == pytest.approx(.8)
    assert row["issuedProbabilityKsGap"] == pytest.approx(1)


def test_issued_unbinned_shift_within_same_bin_detected():
    row = audit_temporal_forecast_calibration(
        fixture(p_early=.71, p_late=.79))["groups"][0]
    assert row["issuedProbabilityJensenShannonBits10"] == pytest.approx(0)
    assert row["issuedProbabilityWasserstein1"] == pytest.approx(.08)
    assert row["issuedProbabilityKsGap"] == pytest.approx(1)


def test_issued_unbinned_shift_ignores_settlement_selection():
    snapshot = fixture(p_early=.10, p_late=.90)
    before = audit_temporal_forecast_calibration(snapshot)["groups"][0]
    for row in snapshot["forecasts"][80:]:
        row.update(status="PENDING", outcomeUp=None, resolvedAt=None)
    after = audit_temporal_forecast_calibration(snapshot)["groups"][0]
    for key in ("issuedProbabilityWasserstein1", "issuedProbabilityKsGap"):
        assert after[key] == before[key]
    assert after["lateBrier"] is None


def test_issued_unbinned_shift_unequal_cohorts_and_empty_support():
    early = [{"probability": .1}, {"probability": .9}]
    late = [{"probability": .5}]
    distance, ks_gap = _issued_probability_ecdf_shift(early, late)
    assert distance == pytest.approx(.4)
    assert ks_gap == pytest.approx(.5)
    assert _issued_probability_ecdf_shift([], late) == (None, None)
    assert _issued_probability_ecdf_shift(early, []) == (None, None)


def test_issued_shape_identical_cohorts_have_zero_signed_shifts():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    assert row["earlyIssuedMeanProbability"] == pytest.approx(.7)
    assert row["issuedProbabilityMeanShift"] == pytest.approx(0)
    assert row["issuedProbabilityMedianShift"] == pytest.approx(0)
    assert row["issuedProbabilityInterdecileRangeShift"] == pytest.approx(0)
    assert row["earlyIssuedHighConfidenceFraction"] == pytest.approx(0)
    assert row["issuedHighConfidenceFractionShift"] == pytest.approx(0)


def test_issued_shape_signed_direction_and_tail_concentration():
    row = audit_temporal_forecast_calibration(
        fixture(p_early=.60, p_late=.95))["groups"][0]
    assert row["earlyIssuedMeanProbability"] == pytest.approx(.60)
    assert row["issuedProbabilityMeanShift"] == pytest.approx(.35)
    assert row["issuedProbabilityMedianShift"] == pytest.approx(.35)
    assert row["issuedProbabilityInterdecileRangeShift"] == pytest.approx(0)
    assert row["earlyIssuedHighConfidenceFraction"] == pytest.approx(0)
    assert row["issuedHighConfidenceFractionShift"] == pytest.approx(1)


def test_issued_shape_spread_widens_without_mean_movement():
    early = [{"probability": .5} for _ in range(40)]
    late = [{"probability": .2 if i % 2 else .8} for i in range(40)]
    row = _issued_probability_shape_shift(early, late)
    assert row["issuedProbabilityMeanShift"] == pytest.approx(0)
    assert row["issuedProbabilityMedianShift"] == pytest.approx(0)
    assert row["issuedProbabilityInterdecileRangeShift"] == pytest.approx(.6)
    assert row["issuedHighConfidenceFractionShift"] == pytest.approx(0)


def test_issued_shape_boundary_confidence_is_inclusive():
    row = _issued_probability_shape_shift(
        [{"probability": .1}, {"probability": .9}],
        [{"probability": .10001}, {"probability": .89999}])
    assert row["earlyIssuedHighConfidenceFraction"] == pytest.approx(1)
    assert row["issuedHighConfidenceFractionShift"] == pytest.approx(-1)


def test_issued_shape_empty_cohort_returns_null_without_imputation():
    early = [{"probability": .5}]
    names = ("earlyIssuedMeanProbability", "issuedProbabilityMeanShift",
             "issuedProbabilityMedianShift", "issuedProbabilityInterdecileRangeShift",
             "earlyIssuedHighConfidenceFraction", "issuedHighConfidenceFractionShift")
    for report in (_issued_probability_shape_shift([], early),
                   _issued_probability_shape_shift(early, [])):
        assert all(report[name] is None for name in names)


def test_issued_shape_independent_of_late_outcome_availability():
    snapshot = fixture(p_early=.6, p_late=.95)
    before = audit_temporal_forecast_calibration(snapshot)["groups"][0]
    for row in snapshot["forecasts"][80:]:
        row.update(status="PENDING", outcomeUp=None, resolvedAt=None)
    after = audit_temporal_forecast_calibration(snapshot)["groups"][0]
    names = ("earlyIssuedMeanProbability", "issuedProbabilityMeanShift",
             "issuedProbabilityMedianShift", "issuedProbabilityInterdecileRangeShift",
             "earlyIssuedHighConfidenceFraction", "issuedHighConfidenceFractionShift")
    assert all(before[name] == after[name] for name in names)
    assert after["lateBrier"] is None


# All observations below are invented, and these are UTC clock-hour bins,
# NOT provider-confirmed trading sessions or an executable market quote.
def _utc_hour_rows(hour, count, probability, day=0):
    return [{"baseStart": day * 86400 + hour * 3600,
             "probability": probability} for _ in range(count)]


def test_utc_hour_composition_only_does_not_fake_within_hour_drift():
    early = _utc_hour_rows(0, 10, .2) + _utc_hour_rows(1, 10, .8)
    late = _utc_hour_rows(0, 2, .2) + _utc_hour_rows(1, 18, .8)
    result = _issued_utc_hour_mix(early, late)
    assert result["issuedUtcHourTotalVariation"] == pytest.approx(.4)
    assert result["issuedUtcHourCommonSupportFraction"] == pytest.approx(.6)
    assert result["issuedUtcHourCommonHourCount"] == 2
    assert result["issuedUtcHourWithinCommonMeanShift"] == pytest.approx(0)
    assert result["issuedUtcHourCommonLowSupportUnder30"] is True
    assert sum(result["earlyIssuedUtcHourCounts24"]) == 20
    assert sum(result["lateIssuedUtcHourCounts24"]) == 20
    assert sum(r["probability"] for r in late) / 20 - sum(
        r["probability"] for r in early) / 20 == pytest.approx(.24)


def test_utc_hour_within_common_shift_uses_fixed_overlap_weights():
    early = _utc_hour_rows(0, 10, .2) + _utc_hour_rows(1, 10, .8)
    late = _utc_hour_rows(0, 10, .4) + _utc_hour_rows(1, 10, .8)
    result = _issued_utc_hour_mix(early, late)
    assert result["issuedUtcHourTotalVariation"] == pytest.approx(0)
    assert result["issuedUtcHourCommonSupportFraction"] == pytest.approx(1)
    assert result["issuedUtcHourWithinCommonMeanShift"] == pytest.approx(.1)


def test_utc_hour_disjoint_support_has_no_fabricated_shift():
    result = _issued_utc_hour_mix(
        _utc_hour_rows(0, 40, .2), _utc_hour_rows(1, 40, .8))
    assert result["issuedUtcHourTotalVariation"] == pytest.approx(1)
    assert result["issuedUtcHourCommonSupportFraction"] == pytest.approx(0)
    assert result["issuedUtcHourCommonHourCount"] == 0
    assert result["issuedUtcHourWithinCommonMeanShift"] is None
    assert result["issuedUtcHourCommonLowSupportUnder30"] is None


def test_utc_hour_empty_cohort_withholds_comparison():
    result = _issued_utc_hour_mix([], _utc_hour_rows(2, 2, .6))
    assert result["issuedUtcHourTotalVariation"] is None
    assert result["issuedUtcHourCommonSupportFraction"] is None
    assert result["issuedUtcHourWithinCommonMeanShift"] is None
    assert result["issuedUtcHourCommonLowSupportUnder30"] is None
    assert sum(result["earlyIssuedUtcHourCounts24"]) == 0
    assert sum(result["lateIssuedUtcHourCounts24"]) == 2


def test_utc_hour_bins_wrap_day_in_utc_not_local_timezone():
    result = _issued_utc_hour_mix(
        _utc_hour_rows(23, 30, .2, day=0),
        _utc_hour_rows(23, 30, .3, day=1))
    assert result["earlyIssuedUtcHourCounts24"][23] == 30
    assert result["lateIssuedUtcHourCounts24"][23] == 30
    assert result["issuedUtcHourWithinCommonMeanShift"] == pytest.approx(.1)
    assert result["issuedUtcHourCommonLowSupportUnder30"] is False


def test_utc_hour_audit_is_outcome_independent_and_never_authorizes_trading():
    original = fixture()
    changed = deepcopy(original)
    for row in changed["forecasts"][100:]:
        row.update(status="PENDING", outcomeUp=None, resolvedAt=None)
    first = audit_temporal_forecast_calibration(original)
    second = audit_temporal_forecast_calibration(changed)
    keys = ("earlyIssuedUtcHourCounts24", "lateIssuedUtcHourCounts24",
            "issuedUtcHourTotalVariation", "issuedUtcHourCommonSupportFraction",
            "issuedUtcHourCommonHourCount", "issuedUtcHourWithinCommonMeanShift",
            "issuedUtcHourCommonLowSupportUnder30")
    for key in keys:
        assert first["groups"][0][key] == second["groups"][0][key]
    assert sum(first["groups"][0]["earlyIssuedUtcHourCounts24"]) == 80
    assert sum(first["groups"][0]["lateIssuedUtcHourCounts24"]) == 80
    assert second["maySendNotification"] is False
    assert second["mayExecutePaperOrder"] is False
    assert second["mayExecuteLiveOrder"] is False


def test_utc_hour_outcome_availability_fixed_census_and_empty_hours():
    row = audit_temporal_forecast_calibration(fixture())["groups"][0]
    early = row["earlyCensusOutcomeAvailabilityUtcHour24"]
    late = row["lateCensusOutcomeAvailabilityUtcHour24"]
    assert len(early) == len(late) == 24
    assert sum(b["issued"] for b in early) == row["earlyNonoverlappingIssued"] == 40
    assert sum(b["issued"] for b in late) == row["lateNonoverlappingIssued"] == 40
    assert (early[0]["issued"], early[1]["issued"]) == (30, 10)
    assert (late[1]["issued"], late[2]["issued"]) == (20, 20)
    assert all(b["unavailable"] == 0 for b in late)
    assert late[3] == {"utcHour": 3, "issued": 0, "eligibleSettled": 0,
                       "unavailable": 0, "unavailableFraction": None,
                       "lowSupportUnder30": None}
    assert early[0]["lowSupportUnder30"] is False
    assert late[1]["lowSupportUnder30"] is True


def test_utc_hour_availability_does_not_shift_census_to_unselected_neighbor():
    s = fixture()
    s["forecasts"][80].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    s["forecasts"][81].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    hour = row["lateCensusOutcomeAvailabilityUtcHour24"][1]
    assert hour["issued"] == 20
    assert hour["eligibleSettled"] == 19
    assert hour["unavailableFraction"] == pytest.approx(1 / 20)
    s["forecasts"][81].update(status="SETTLED", outcomeUp=True, resolvedAt=5040)
    again = audit_temporal_forecast_calibration(s)["groups"][0]
    assert (again["lateCensusOutcomeAvailabilityUtcHour24"] ==
            row["lateCensusOutcomeAvailabilityUtcHour24"])


def test_utc_hour_early_availability_purges_post_boundary_label():
    s = fixture()
    s["forecasts"][78]["resolvedAt"] = s["forecasts"][80]["issuedAt"]
    row = audit_temporal_forecast_calibration(s)["groups"][0]
    hour = row["earlyCensusOutcomeAvailabilityUtcHour24"][1]
    assert hour["issued"] == 10
    assert hour["eligibleSettled"] == 9
    assert hour["unavailable"] == 1
    assert row["earlyCensusUnavailableAtBoundary"] == 1


def test_utc_hour_late_availability_respects_declared_as_of():
    s = fixture()
    cutoff = max(r["issuedAt"] for r in s["forecasts"])
    s["forecasts"][80]["resolvedAt"] = cutoff + 120
    row = audit_temporal_forecast_calibration(
        s, evaluation_as_of=cutoff)["groups"][0]
    hour = row["lateCensusOutcomeAvailabilityUtcHour24"][1]
    assert hour["issued"] == 20 and hour["eligibleSettled"] == 19
    assert hour["unavailable"] == row["lateCensusSettledAfterDeclaredAsOf"] == 1


def test_utc_hour_availability_visible_when_scores_withheld():
    row = audit_temporal_forecast_calibration(
        fixture(horizon=12))["groups"][0]
    assert row["status"] == "INSUFFICIENT_NONOVERLAPPING_OUTCOMES"
    assert row["lateBrier"] is None
    assert (sum(b["issued"] for b in row["lateCensusOutcomeAvailabilityUtcHour24"])
            == row["lateNonoverlappingIssued"])


def test_utc_hour_availability_uses_utc_day_rollover_and_no_outcome_direction():
    from app.forecast_temporal_calibration_audit import _outcome_availability_utc_hour24
    rows = [{"id": "a", "baseStart": 23 * 3600},
            {"id": "b", "baseStart": 24 * 3600},
            {"id": "c", "baseStart": 25 * 3600}]
    bins = _outcome_availability_utc_hour24(rows, [rows[0], rows[2]])
    assert bins[23]["eligibleSettled"] == 1
    assert bins[0]["issued"] == 1 and bins[0]["unavailable"] == 1
    assert bins[1]["eligibleSettled"] == 1
    assert bins[2]["unavailableFraction"] is None
    assert sum(b["issued"] for b in bins) == 3
