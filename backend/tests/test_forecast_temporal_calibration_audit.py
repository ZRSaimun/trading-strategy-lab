"""Invented observations only; never a live forecast or paper-trading return."""
from copy import deepcopy
import pytest

from app.forecast_temporal_calibration_audit import audit_temporal_forecast_calibration

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
