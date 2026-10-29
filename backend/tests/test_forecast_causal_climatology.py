"""Synthetic-only prequential baseline tests; no broker or market calls."""
from copy import deepcopy
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
