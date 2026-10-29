"""Synthetic-only prequential baseline tests; no broker or market calls."""
from copy import deepcopy
import math
import pytest
from app.forecast_causal_climatology import audit_causal_climatology

IDENTITY = {"instrument": "SYNTH", "provider": "FAKE", "venue": "TEST",
            "sourceId": "causal", "priceSide": "bid", "seconds": 60}


def fixture(n=240, horizon=1, p=.7, outcome=True):
    events, forecasts = [], []
    for i in range(n):
        base = 60 * (i + 1)
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": "frozen",
                       "horizon": horizon, "probability": p,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": "frozen", "horizon": horizon,
                          "probability": p, "baseStart": base, "baseClose": 100,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "SETTLED", "resolvedAt": base + (horizon + 1) * 60,
                          "outcomeUp": outcome})
    return {"sequence": len(events), "identity": IDENTITY.copy(),
            "maxLagSeconds": 60, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def run(s, **kwargs):
    return audit_causal_climatology(s, evaluation_as_of=200000, **kwargs)


def test_paired_losses_descriptive_only():
    row = run(fixture())["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["scored"] >= 30
    assert row["causalBaselineBrier"] < row["issuedBrier"]
    assert row["pairedBrierRegretIssuedMinusBaseline"] > 0
    assert row["pairedLogLossRegretIssuedMinusBaseline"] > 0


def test_never_authorizes_execution_or_claims_returns():
    report = run(fixture())
    assert not any(report[k] for k in (
        "sourceAuthenticated", "evaluationCutoffAuthenticated",
        "maySendNotification", "mayExecutePaperOrder", "mayExecuteLiveOrder",
        "profitabilityEstablished"))
    assert report["netPaperReturn"] is None and report["maximumDrawdown"] is None


def test_future_labels_cannot_change_first_causal_prediction():
    s = fixture()
    first = run(s)["groups"][0]["firstScoredBaselineProbability"]
    for row in s["forecasts"][100:]:
        row["outcomeUp"] = False
    assert run(s)["groups"][0]["firstScoredBaselineProbability"] == first


def test_delayed_receipt_cannot_enter_early_training():
    s = fixture()
    s["forecasts"][0]["resolvedAt"] = 200001
    a = run(fixture())["groups"][0]
    b = run(s)["groups"][0]
    assert b["firstScoredBaselineProbability"] == a["firstScoredBaselineProbability"]
    assert b["minCausalTrainingOutcomes"] >= 30


def test_pending_and_void_never_scored():
    s = fixture()
    # For horizon 1, disjoint scoring selects indices 0, 2, ..., 238.
    s["forecasts"][-2].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    s["forecasts"][-4].update(status="VOID_GAP", outcomeUp=None)
    row = run(s)["groups"][0]
    assert row["unavailable"] == 2
    assert row["scored"] == row["baselineEligible"] - 2


def test_cutoff_excludes_unmatured_targets():
    s = fixture()
    cutoff = s["forecasts"][-1]["issuedAt"]
    row = audit_causal_climatology(s, evaluation_as_of=cutoff)["groups"][0]
    assert row["maturedAtDeclaredCutoff"] < len(s["forecasts"])


def test_long_horizon_withholds_insufficient_nonoverlapping_support():
    row = run(fixture(horizon=12))["groups"][0]
    assert row["status"] == "INSUFFICIENT_CAUSAL_SAMPLE"
    assert row["issuedBrier"] is None


def test_model_and_horizon_never_pool():
    s = fixture()
    other = fixture(n=240, horizon=3, p=.2, outcome=False)
    for e, f in zip(other["events"], other["forecasts"]):
        e["id"] += "x"
        e["modelVersion"] = "other"
        f["id"] += "x"
        f["modelVersion"] = "other"
    s["events"] += other["events"]
    s["forecasts"] += other["forecasts"]
    s["sequence"] = len(s["events"])
    assert [(g["modelVersion"], g["horizonCandles"]) for g in run(s)["groups"]] == [
        ("frozen", 1), ("other", 3)]


def test_repeated_base_rejected():
    s = fixture()
    s["forecasts"][1]["baseStart"] = s["events"][1]["baseStart"] = s["forecasts"][0]["baseStart"]
    s["forecasts"][1]["targetStart"] = s["forecasts"][0]["targetStart"]
    with pytest.raises(ValueError):
        run(s)


@pytest.mark.parametrize("bad", [
    {"evaluation_as_of": True}, {"evaluation_as_of": -1},
    {"evaluation_as_of": 0}, {"min_training": 29}, {"min_training": True},
    {"min_scored": 0}, {"max_unavailable_fraction": 1},
    {"max_unavailable_fraction": float("nan")},
    {"max_unavailable_fraction": True},
])
def test_invalid_configuration_rejected(bad):
    if "evaluation_as_of" not in bad:
        bad = {"evaluation_as_of": 200000, **bad}
    with pytest.raises(ValueError):
        audit_causal_climatology(fixture(), **bad)


def test_no_mutation_and_empty_population():
    s = fixture()
    original = deepcopy(s)
    run(s)
    assert s == original
    assert run(fixture(0))["groups"] == []


def test_selection_risk_withholds_scores():
    s = fixture()
    for row in s["forecasts"][-70:]:
        row.update(status="PENDING", resolvedAt=None, outcomeUp=None)
    row = run(s)["groups"][0]
    assert row["status"] == "UNAVAILABLE_OUTCOME_SELECTION_RISK"
    assert row["issuedBrier"] is None


def test_disjoint_evaluation_census_cannot_inflate_minimum_scored():
    # 100 matured h=1 forecasts share 50 base/target boundary closes.
    # A naive all-issuance count would have >=30 scored after training;
    # the fixed disjoint census has fewer than 30 and must abstain.
    row = run(fixture(n=100))["groups"][0]
    assert row["maturedAtDeclaredCutoff"] == 100
    assert row["nonoverlappingMaturedCensus"] == 50
    assert row["overlappingMaturedExcluded"] == 50
    assert row["scored"] < 30
    assert row["status"] == "INSUFFICIENT_CAUSAL_SAMPLE"
    assert row["pairedBrierRegretIssuedMinusBaseline"] is None


def test_longer_horizon_disjoint_scoring_has_no_overlap():
    row = run(fixture(n=360, horizon=3))["groups"][0]
    assert row["maturedAtDeclaredCutoff"] == 360
    assert row["nonoverlappingMaturedCensus"] == 90
    assert row["overlappingMaturedExcluded"] == 270
    assert row["scored"] <= row["nonoverlappingMaturedCensus"]
    assert row["scored"] >= 30


def test_outcome_status_cannot_reselect_disjoint_evaluation_members():
    base = run(fixture())["groups"][0]
    s = fixture()
    # Unselected indices are excluded regardless of whether they settle.
    for index in (237, 239):
        s["forecasts"][index].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    changed = run(s)["groups"][0]
    assert changed["nonoverlappingMaturedCensus"] == base["nonoverlappingMaturedCensus"]
    assert changed["scored"] == base["scored"]
    assert changed["unavailable"] == base["unavailable"]


def test_complete_eligible_census_bounds_equal_observed_paired_regret():
    row = run(fixture())["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["unavailable"] == 0
    assert row["pairedBrierRegretBestCaseEligibleCensus"] == pytest.approx(
        row["pairedBrierRegretIssuedMinusBaseline"])
    assert row["pairedBrierRegretWorstCaseEligibleCensus"] == pytest.approx(
        row["pairedBrierRegretIssuedMinusBaseline"])
    assert row["pairedLogLossRegretBestCaseEligibleCensus"] == pytest.approx(
        row["pairedLogLossRegretIssuedMinusBaseline"])
    assert row["pairedLogLossRegretWorstCaseEligibleCensus"] == pytest.approx(
        row["pairedLogLossRegretIssuedMinusBaseline"])


@pytest.mark.parametrize("missing", ["PENDING", "VOID_GAP", "POST_CUTOFF"])
def test_counterfactual_regret_bounds_on_fixed_eligible_census(missing):
    complete = run(fixture())["groups"][0]
    s = fixture()
    last = s["forecasts"][238]  # Last selected disjoint evaluation row.
    if missing == "PENDING":
        last.update(status="PENDING", resolvedAt=None, outcomeUp=None)
    elif missing == "VOID_GAP":
        last.update(status="VOID_GAP", resolvedAt=last["issuedAt"], outcomeUp=None)
    else:
        last.update(status="SETTLED", resolvedAt=200001, outcomeUp=True)
    row = run(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["baselineEligible"] == complete["baselineEligible"]
    assert row["scored"] == complete["scored"] - 1
    assert row["unavailable"] == 1
    # The missing final row's baseline uses 119 prior disjoint UP outcomes.
    p, q = 119.5 / 120, .7
    brier_down, brier_up = q * q - p * p, (1 - q) ** 2 - (1 - p) ** 2
    log_down = math.log1p(-p) - math.log1p(-q)
    log_up = math.log(p) - math.log(q)
    observed_brier = (complete["pairedBrierRegretIssuedMinusBaseline"]
                      * complete["scored"] - brier_up)
    observed_log = (complete["pairedLogLossRegretIssuedMinusBaseline"]
                    * complete["scored"] - log_up)
    assert row["pairedBrierRegretBestCaseEligibleCensus"] == pytest.approx(
        (observed_brier + min(brier_down, brier_up)) / row["baselineEligible"])
    assert row["pairedBrierRegretWorstCaseEligibleCensus"] == pytest.approx(
        (observed_brier + max(brier_down, brier_up)) / row["baselineEligible"])
    assert row["pairedLogLossRegretBestCaseEligibleCensus"] == pytest.approx(
        (observed_log + min(log_down, log_up)) / row["baselineEligible"])
    assert row["pairedLogLossRegretWorstCaseEligibleCensus"] == pytest.approx(
        (observed_log + max(log_down, log_up)) / row["baselineEligible"])


def test_counterfactual_regret_bounds_withheld_when_not_sufficient():
    row = run(fixture(n=100))["groups"][0]
    for metric in ("pairedBrierRegretBestCaseEligibleCensus",
                   "pairedBrierRegretWorstCaseEligibleCensus",
                   "pairedLogLossRegretBestCaseEligibleCensus",
                   "pairedLogLossRegretWorstCaseEligibleCensus"):
        assert row[metric] is None


def test_disjoint_temporal_split_reports_descriptive_regime_change_only():
    row = run(fixture())["groups"][0]
    assert row["temporalSplitStatus"] == "DESCRIPTIVE_ONLY"
    assert row["temporalSplitEarlyCount"] + row["temporalSplitLateCount"] == row["scored"]
    assert row["temporalSplitEarlyCount"] >= 30
    assert row["temporalSplitLateCount"] >= 30
    assert row["pairedBrierRegretLateMinusEarly"] == pytest.approx(
        row["pairedBrierRegretLateHalf"] - row["pairedBrierRegretEarlyHalf"])
    assert row["pairedLogLossRegretLateMinusEarly"] == pytest.approx(
        row["pairedLogLossRegretLateHalf"] - row["pairedLogLossRegretEarlyHalf"])


def test_temporal_split_withheld_for_missing_eligible_label_even_if_primary_scored():
    s = fixture()
    s["forecasts"][238].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    row = run(s)["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["temporalSplitStatus"] == "MISSING_ELIGIBLE_OUTCOMES"
    assert row["pairedBrierRegretEarlyHalf"] is None
    assert row["pairedLogLossRegretLateMinusEarly"] is None
    assert row["temporalSplitEarlyCount"] is None


def test_temporal_split_requires_thirty_disjoint_scores_per_half():
    row = run(fixture(n=130))["groups"][0]
    assert row["status"] == "DESCRIPTIVE_ONLY"
    assert row["temporalSplitStatus"] == "INSUFFICIENT_TEMPORAL_SPLIT_SAMPLE"
    assert row["pairedBrierRegretLateMinusEarly"] is None


def test_later_outcome_does_not_rewrite_earlier_temporal_split():
    s = fixture()
    earlier = run(s)["groups"][0]
    s["forecasts"][238]["outcomeUp"] = False
    later = run(s)["groups"][0]
    assert earlier["pairedBrierRegretEarlyHalf"] == later["pairedBrierRegretEarlyHalf"]
    assert earlier["pairedLogLossRegretEarlyHalf"] == later["pairedLogLossRegretEarlyHalf"]
    assert earlier["pairedBrierRegretLateHalf"] != later["pairedBrierRegretLateHalf"]


def test_temporal_calibration_gap_is_signed_and_disjoint():
    row = run(fixture())["groups"][0]
    assert row["temporalSplitStatus"] == "DESCRIPTIVE_ONLY"
    assert row["temporalSplitEarlyCount"] == row["temporalSplitLateCount"] == 60
    assert row["temporalSplitMeanIssuedProbabilityEarlyHalf"] == pytest.approx(.7)
    assert row["temporalSplitMeanIssuedProbabilityLateHalf"] == pytest.approx(.7)
    assert row["temporalSplitObservedUpFractionEarlyHalf"] == pytest.approx(1)
    assert row["temporalSplitObservedUpFractionLateHalf"] == pytest.approx(1)
    assert row["temporalSplitSignedCalibrationGapEarlyHalf"] == pytest.approx(-.3)
    assert row["temporalSplitSignedCalibrationGapLateHalf"] == pytest.approx(-.3)
    assert row["temporalSplitSignedCalibrationGapLateMinusEarly"] == pytest.approx(0)


def test_temporal_calibration_detects_late_outcome_shift_without_rewriting_early():
    s = fixture()
    for index in range(120, 240, 2):
        s["forecasts"][index]["outcomeUp"] = False
    row = run(s)["groups"][0]
    assert row["temporalSplitObservedUpFractionEarlyHalf"] == pytest.approx(1)
    assert row["temporalSplitObservedUpFractionLateHalf"] == pytest.approx(0)
    assert row["temporalSplitSignedCalibrationGapEarlyHalf"] == pytest.approx(-.3)
    assert row["temporalSplitSignedCalibrationGapLateHalf"] == pytest.approx(.7)
    assert row["temporalSplitSignedCalibrationGapLateMinusEarly"] == pytest.approx(1)


def test_temporal_calibration_detects_issued_probability_shift():
    s = fixture()
    for event, row in zip(s["events"][120:], s["forecasts"][120:]):
        event["probability"] = row["probability"] = .3
    result = run(s)["groups"][0]
    assert result["temporalSplitMeanIssuedProbabilityEarlyHalf"] == pytest.approx(.7)
    assert result["temporalSplitMeanIssuedProbabilityLateHalf"] == pytest.approx(.3)
    assert result["temporalSplitSignedCalibrationGapLateMinusEarly"] == pytest.approx(-.4)


@pytest.mark.parametrize("mutate", ["missing", "too_few"])
def test_temporal_calibration_withheld_under_split_gates(mutate):
    s = fixture() if mutate == "missing" else fixture(n=130)
    if mutate == "missing":
        s["forecasts"][238].update(status="PENDING", resolvedAt=None, outcomeUp=None)
    row = run(s)["groups"][0]
    assert row["temporalSplitStatus"] != "DESCRIPTIVE_ONLY"
    for key in (
        "temporalSplitMeanIssuedProbabilityEarlyHalf",
        "temporalSplitMeanIssuedProbabilityLateHalf",
        "temporalSplitObservedUpFractionEarlyHalf",
        "temporalSplitObservedUpFractionLateHalf",
        "temporalSplitSignedCalibrationGapEarlyHalf",
        "temporalSplitSignedCalibrationGapLateHalf",
        "temporalSplitSignedCalibrationGapLateMinusEarly",
    ):
        assert row[key] is None
