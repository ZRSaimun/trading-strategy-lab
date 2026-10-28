"""Synthetic scorecard regressions. No live feed, real prices, or trading returns."""
from copy import deepcopy
import math
import pytest

from app.forecast_prospective_scorecard import summarize_forecast_snapshot, audit_settled_receipt_lag

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC", "venue": "TEST",
            "sourceId": "scorecard", "priceSide": "bid", "seconds": 60}


def snapshot(n=30, status="SETTLED", p=0.7, outcome=True):
    forecasts, events = [], []
    for i in range(n):
        start = 60 * (i + 1)
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": "baseline",
                       "horizon": 1, "probability": p, "baseStart": start, "receivedAt": start + 60})
        forecasts.append({"id": fid, "modelVersion": "baseline", "horizon": 1,
                          "probability": p, "baseStart": start, "baseClose": 100,
                          "issuedAt": start + 60, "targetStart": start + 60,
                          "status": status, "resolvedAt": start + 120 if status != "PENDING" else None,
                          "outcomeUp": outcome if status == "SETTLED" else None})
    return {"sequence": len(events), "identity": IDENTITY.copy(), "maxLagSeconds": 120,
            "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def group(s, **kwargs):
    return summarize_forecast_snapshot(s, **kwargs)["groups"][0]


def test_perfect_synthetic_scores_not_trading_returns():
    result = summarize_forecast_snapshot(snapshot())
    row = result["groups"][0]
    assert row["issued"] == row["settled"] == 30
    assert row["directionAccuracy"] == 1.0
    assert row["brier"] == pytest.approx(0.09)
    assert row["logLoss"] == pytest.approx(-math.log(.7))
    assert row["expectedCalibrationError"] == pytest.approx(.3)
    assert result["netReturn"] is None and result["maximumDrawdown"] is None
    assert result["sourceAuthenticated"] is False and result["profitabilityEstablished"] is False


def test_no_misleading_small_sample_metrics():
    row = group(snapshot(29))
    assert not row["sufficientSample"]
    assert row["directionAccuracy"] is None and row["brier"] is None


def test_pending_and_gap_remain_denominator():
    s = snapshot(30)
    s["forecasts"][0].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    s["forecasts"][1].update(status="VOID_GAP", outcomeUp=None)
    row = group(s)
    assert (row["issued"], row["settled"], row["pending"], row["voidGap"]) == (30, 28, 1, 1)
    assert row["settledFractionOfIssued"] == pytest.approx(28 / 30)
    assert row["brier"] is None


def test_half_probability_is_abstention():
    row = group(snapshot(p=.5))
    assert row["directionalCalls"] == 0
    assert row["directionAccuracy"] is None and row["wilson95Descriptive"] is None
    assert row["brier"] == .25


def test_wrong_calls_and_wilson_bounds():
    row = group(snapshot(outcome=False))
    assert row["directionAccuracy"] == 0
    assert row["wilson95Descriptive"][0] == 0
    assert 0 < row["wilson95Descriptive"][1] < .2


def test_multiple_horizons_and_models_are_not_pooled():
    s = snapshot()
    t = snapshot(30, p=.2, outcome=False)
    for event, forecast in zip(t["events"], t["forecasts"]):
        event["id"] += "b"
        event["horizon"] = 3
        event["modelVersion"] = "model-b"
        forecast["id"] += "b"
        forecast["horizon"] = 3
        forecast["targetStart"] = forecast["baseStart"] + 180
        forecast["resolvedAt"] = forecast["targetStart"] + 60
        forecast["modelVersion"] = "model-b"
    s["events"].extend(t["events"])
    s["forecasts"].extend(t["forecasts"])
    s["sequence"] = len(s["events"])
    assert [(r["modelVersion"], r["horizonCandles"]) for r in summarize_forecast_snapshot(s)["groups"]] == [
        ("baseline", 1), ("model-b", 3)]


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(evidence="AUTHENTICATED_LIVE"),
    lambda s: s.update(sequence=999),
    lambda s: s["forecasts"][0].update(probability=float("nan")),
    lambda s: s["forecasts"][0].update(probability=1),
    lambda s: s["forecasts"][0].update(outcomeUp=1),
    lambda s: s["forecasts"][0].update(targetStart=999),
    lambda s: s["forecasts"][0].update(resolvedAt=0),
    lambda s: s["forecasts"][0].update(status="DELIVERED"),
    lambda s: s["forecasts"][0].update(id="unknown"),
    lambda s: s["events"].append(s["events"][0]),
    lambda s: s["identity"].update(priceSide="executable"),
])
def test_fail_closed_inconsistent_snapshots(mutation):
    s = snapshot()
    mutation(s)
    with pytest.raises(ValueError):
        summarize_forecast_snapshot(s)


@pytest.mark.parametrize("min_settled,calibration_bins", [(29, 10), (True, 10), (30, 1), (30, 21), (30, True)])
def test_rejects_invalid_scorecard_settings(min_settled, calibration_bins):
    with pytest.raises(ValueError):
        summarize_forecast_snapshot(snapshot(), min_settled=min_settled, calibration_bins=calibration_bins)


def test_empty_validated_journal():
    s = snapshot(0)
    result = summarize_forecast_snapshot(s)
    assert result["groups"] == [] and result["issuedTotal"] == 0


@pytest.mark.parametrize("invalid_lag", [-1, 3601, True, 0.5, None, "120"])
def test_rejects_forged_maximum_receipt_lag(invalid_lag):
    s = snapshot()
    s["maxLagSeconds"] = invalid_lag
    with pytest.raises(ValueError, match="maximum receipt lag"):
        summarize_forecast_snapshot(s)


@pytest.mark.parametrize("base,issued", [
    (61, 121),           # base candle is not UTC-duration aligned
    (60, 119),           # forecast predates completed base candle
    (60, 181),           # forecast is after the next candle closed
    (60, 180),           # upper issuance window is exclusive
    (-60, 0),            # invalid epoch
    (2**53, 2**53 + 60), # epoch overflow
])
def test_rejects_forged_issuance_chronology(base, issued):
    s = snapshot()
    row, event = s["forecasts"][0], s["events"][0]
    row["baseStart"] = event["baseStart"] = base
    row["issuedAt"] = event["receivedAt"] = issued
    row["targetStart"] = base + 60
    with pytest.raises(ValueError, match="resolution"):
        summarize_forecast_snapshot(s)


def test_rejects_forecast_issued_after_declared_lag():
    s = snapshot()
    s["maxLagSeconds"] = 10
    s["forecasts"][0]["issuedAt"] = s["events"][0]["receivedAt"] = 71 + 60
    with pytest.raises(ValueError, match="resolution"):
        summarize_forecast_snapshot(s)


def test_valid_completed_candle_issuance_inside_declared_window():
    s = snapshot()
    s["maxLagSeconds"] = 59
    s["forecasts"][0]["issuedAt"] = s["events"][0]["receivedAt"] = 60 + 60 + 59
    # A later issuedAt remains before the already-declared settlement receipt.
    assert group(s)["settled"] == 30


@pytest.mark.parametrize("resolved,accepted", [
    (179, False),          # Target starts at 120; cannot settle before close at 180.
    (180, True),           # Exact target close is chronologically eligible.
    (181, True),           # Later declared settlement is possible.
    (True, False),         # Booleans must not masquerade as epoch integers.
    (2**53, False),        # Exceeds the bounded timestamp representation.
])
def test_settled_receipt_must_follow_target_close(resolved, accepted):
    s = snapshot()
    s["forecasts"][0]["resolvedAt"] = resolved
    if accepted:
        assert group(s)["settled"] == 30
    else:
        with pytest.raises(ValueError, match="resolution"):
            summarize_forecast_snapshot(s)


def test_horizon_three_settlement_must_wait_for_its_own_target_close():
    s = snapshot()
    row, event = s["forecasts"][0], s["events"][0]
    row["horizon"] = event["horizon"] = 3
    row["targetStart"] = row["baseStart"] + 3 * IDENTITY["seconds"]
    row["resolvedAt"] = row["targetStart"] + IDENTITY["seconds"] - 1
    with pytest.raises(ValueError, match="resolution"):
        summarize_forecast_snapshot(s)
    row["resolvedAt"] += 1
    assert sum(g["settled"] for g in summarize_forecast_snapshot(s)["groups"]) == 30


def test_gap_void_may_be_known_before_future_target_close():
    s = snapshot()
    row, event = s["forecasts"][0], s["events"][0]
    row["horizon"] = event["horizon"] = 3
    row["targetStart"] = row["baseStart"] + 3 * IDENTITY["seconds"]
    row.update(status="VOID_GAP", outcomeUp=None, resolvedAt=row["targetStart"])
    groups = summarize_forecast_snapshot(s)["groups"]
    assert sum(g["voidGap"] for g in groups) == 1
    row["resolvedAt"] = 2**53
    with pytest.raises(ValueError, match="resolution"):
        summarize_forecast_snapshot(s)


@pytest.mark.parametrize("horizon,lag", [
    (1, 0), (1, 1), (1, 120), (3, 0), (3, 120), (12, 0), (12, 3600),
])
def test_opt_in_settlement_lag_audit_respects_inclusive_deadline(horizon, lag):
    s = snapshot()
    s["maxLagSeconds"] = lag
    row, event = s["forecasts"][0], s["events"][0]
    row["horizon"] = event["horizon"] = horizon
    row["targetStart"] = row["baseStart"] + horizon * IDENTITY["seconds"]
    deadline = row["targetStart"] + IDENTITY["seconds"] + lag
    row["resolvedAt"] = deadline
    assert audit_settled_receipt_lag(s)["lateBeyondDeclaredLagCount"] == 0
    row["resolvedAt"] = deadline + 1
    result = audit_settled_receipt_lag(s)
    assert result["status"] == "DECLARED_SETTLEMENT_LAG_VIOLATIONS"
    assert result["settledCount"] == 30
    assert result["lateBeyondDeclaredLagCount"] == 1
    assert result["largestExcessSeconds"] == 1
    assert result["sourceAuthenticated"] is False
    assert result["mayExecuteLiveOrder"] is False


def test_opt_in_receipt_lag_audit_excludes_gap_voids():
    s = snapshot()
    row = s["forecasts"][0]
    row.update(status="VOID_GAP", outcomeUp=None,
               resolvedAt=row["targetStart"] + IDENTITY["seconds"] + 3601)
    result = audit_settled_receipt_lag(s)
    assert result["settledCount"] == 29
    assert result["lateBeyondDeclaredLagCount"] == 0
    assert result["largestExcessSeconds"] is None


def test_opt_in_receipt_lag_audit_empty_and_invalid_journals():
    assert audit_settled_receipt_lag(snapshot(0))["status"] == "NO_SETTLED_OUTCOMES"
    s = snapshot()
    s["forecasts"][0]["resolvedAt"] = -1
    with pytest.raises(ValueError, match="resolution"):
        audit_settled_receipt_lag(s)


def test_settlement_lag_audit_model_horizon_breakdown_is_reconciled():
    s = snapshot(5)
    for index, horizon in ((0, 3), (1, 12)):
        row, event = s["forecasts"][index], s["events"][index]
        row["horizon"] = event["horizon"] = horizon
        row["targetStart"] = row["baseStart"] + horizon * IDENTITY["seconds"]
    s["forecasts"][0]["resolvedAt"] = s["forecasts"][0]["targetStart"] + 60 + 120 + 4
    s["forecasts"][1]["resolvedAt"] = s["forecasts"][1]["targetStart"] + 60 + 120
    s["forecasts"][2]["modelVersion"] = s["events"][2]["modelVersion"] = "alt"
    s["forecasts"][2]["resolvedAt"] = s["forecasts"][2]["targetStart"] + 60 + 120 + 1
    s["forecasts"][3].update(status="VOID_GAP", outcomeUp=None,
                             resolvedAt=s["forecasts"][3]["targetStart"] + 60 + 4000)
    s["forecasts"][4].update(status="PENDING", outcomeUp=None, resolvedAt=None)

    result = audit_settled_receipt_lag(s)
    assert result["settledCount"] == 3
    assert result["lateBeyondDeclaredLagCount"] == 2
    assert result["largestExcessSeconds"] == 4
    assert result["byModelHorizon"] == [
        {"modelVersion": "alt", "horizonCandles": 1, "settledCount": 1,
         "lateBeyondDeclaredLagCount": 1, "lateFractionOfSettled": 1.0,
         "largestExcessSeconds": 1, "receiptDelaySecondsP50": 121,
         "receiptDelaySecondsP95": 121},
        {"modelVersion": "baseline", "horizonCandles": 3, "settledCount": 1,
         "lateBeyondDeclaredLagCount": 1, "lateFractionOfSettled": 1.0,
         "largestExcessSeconds": 4, "receiptDelaySecondsP50": 124,
         "receiptDelaySecondsP95": 124},
        {"modelVersion": "baseline", "horizonCandles": 12, "settledCount": 1,
         "lateBeyondDeclaredLagCount": 0, "lateFractionOfSettled": 0.0,
         "largestExcessSeconds": None, "receiptDelaySecondsP50": 120,
         "receiptDelaySecondsP95": 120},
    ]
    assert sum(g["settledCount"] for g in result["byModelHorizon"]) == result["settledCount"]
    assert (sum(g["lateBeyondDeclaredLagCount"] for g in result["byModelHorizon"])
            == result["lateBeyondDeclaredLagCount"])


def test_settlement_lag_audit_breakdown_empty_or_all_on_time():
    assert audit_settled_receipt_lag(snapshot(0))["byModelHorizon"] == []
    result = audit_settled_receipt_lag(snapshot(30))
    assert result["byModelHorizon"] == [
        {"modelVersion": "baseline", "horizonCandles": 1, "settledCount": 30,
         "lateBeyondDeclaredLagCount": 0, "lateFractionOfSettled": 0.0,
         "largestExcessSeconds": None, "receiptDelaySecondsP50": 0,
         "receiptDelaySecondsP95": 0},
    ]


def test_settlement_lag_audit_breakdown_preserves_fail_closed_validation():
    s = snapshot()
    s["forecasts"][0]["modelVersion"] = "forged"
    with pytest.raises(ValueError, match="issuance/outcome mismatch"):
        audit_settled_receipt_lag(s)


def test_settlement_lag_declared_delay_percentiles_nearest_rank():
    s = snapshot(20)
    for index, row in enumerate(s["forecasts"]):
        row["resolvedAt"] = row["targetStart"] + IDENTITY["seconds"] + index
    result = audit_settled_receipt_lag(s)
    assert (result["receiptDelaySecondsP50"], result["receiptDelaySecondsP95"]) == (9, 18)
    assert result["byModelHorizon"][0]["receiptDelaySecondsP50"] == 9
    assert result["byModelHorizon"][0]["receiptDelaySecondsP95"] == 18
    assert result["lateBeyondDeclaredLagCount"] == 0
    assert result["sourceAuthenticated"] is False
    assert result["maySendNotification"] is False


def test_settlement_lag_declared_delay_percentiles_exclude_pending_and_void():
    s = snapshot(4)
    s["forecasts"][0]["resolvedAt"] += 20
    s["forecasts"][1]["resolvedAt"] += 100
    s["forecasts"][2].update(status="PENDING", outcomeUp=None, resolvedAt=None)
    s["forecasts"][3].update(status="VOID_GAP", outcomeUp=None, resolvedAt=100000)
    result = audit_settled_receipt_lag(s)
    # For n=2, nearest-rank P50 is the first and P95 is the second.
    assert result["settledCount"] == 2
    assert (result["receiptDelaySecondsP50"], result["receiptDelaySecondsP95"]) == (20, 100)
    assert result["byModelHorizon"][0]["receiptDelaySecondsP95"] == 100


def test_settlement_lag_declared_delay_percentiles_empty_are_null():
    result = audit_settled_receipt_lag(snapshot(0))
    assert result["receiptDelaySecondsP50"] is None
    assert result["receiptDelaySecondsP95"] is None
    assert result["byModelHorizon"] == []


def test_settlement_lag_declared_delay_percentiles_include_late_receipts():
    s = snapshot(2)
    s["forecasts"][0]["resolvedAt"] += 121
    result = audit_settled_receipt_lag(s)
    assert result["lateBeyondDeclaredLagCount"] == 1
    assert result["receiptDelaySecondsP50"] == 0
    assert result["receiptDelaySecondsP95"] == 121
    assert result["byModelHorizon"][0]["receiptDelaySecondsP95"] == 121
