"""Synthetic causal replay regression; no network, broker or production state."""
from copy import deepcopy

import pytest

from app.forecast_causal_issuer import MODEL_VERSION, _training
from app.forecast_event_store import _replay
from app.forecast_jeffreys_replay_audit import audit_jeffreys_causal_replay as audit


IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC",
            "venue": "TEST", "sourceId": "synthetic-only", "priceSide": "bid",
            "seconds": 60}
MODEL = f"{MODEL_VERSION}-n30"


def fixture(count=45, *, horizons=(1,), emit=True, gap_at=None, model=MODEL):
    events, candles = [], []
    for i in range(count):
        start = (i + 1 + int(gap_at is not None and i >= gap_at)) * 60
        close = 100.0 + (i % 9) - (i // 17) * .2
        candles.append({"start": start, "close": close})
        events.append({"seq": len(events) + 1, "receivedAt": start + 60,
                       "kind": "CANDLE", "start": start, "close": close})
        for h in horizons:
            up, n = _training(candles, 60, h)
            if n >= 30 and emit and (emit is True or i == count - 1):
                events.append({"seq": len(events) + 1, "receivedAt": start + 60,
                               "kind": "FORECAST", "id": f"f_{h}_{start}",
                               "modelVersion": model, "horizon": h,
                               "probability": (up + .5) / (n + 1),
                               "baseStart": start})
    forecasts = _replay({"version": 1, "identity": IDENTITY,
                         "maxLagSeconds": 0, "events": events},
                        events[-1]["receivedAt"] if events else 0)
    return {"sequence": len(events), "identity": IDENTITY.copy(),
            "maxLagSeconds": 0, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def rebuild(s):
    s["forecasts"] = _replay({"version": 1, "identity": s["identity"],
                              "maxLagSeconds": s["maxLagSeconds"],
                              "events": s["events"]},
                             s["events"][-1]["receivedAt"] if s["events"] else 0)
    return s


def test_exact_replay_is_read_only():
    s = fixture(60)
    before = deepcopy(s)
    r = audit(s)
    assert s == before
    assert r["status"] == "DECLARED_CAUSAL_REPLAY_MATCH_UNVERIFIED"
    assert r["recordedModelIssuances"] == r["exactProbabilityMatches"] > 0
    assert r["probabilityMismatchCount"] == r["insufficientTrainingIssuanceCount"] == 0
    assert all(r[k] is False for k in (
        "sourceAuthenticated", "independentScheduleVerified", "modelCalibrationVerified",
        "forwardReturnsVerified", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_three_horizons_exact_causal_training():
    r = audit(fixture(390, horizons=(1, 3, 12)))
    assert r["status"] == "DECLARED_CAUSAL_REPLAY_MATCH_UNVERIFIED"
    assert all(x["issued"] > 0 and x["issued"] == x["matched"]
               for x in r["byHorizon"])
    assert r["probabilityMismatchCount"] == 0


def test_modified_probability_detected_even_when_journal_is_self_consistent():
    s = fixture()
    forecast = next(e for e in s["events"] if e["kind"] == "FORECAST")
    forecast["probability"] = .999
    rebuild(s)
    r = audit(s)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["probabilityMismatchCount"] == 1
    assert r["first50ProbabilityMismatches"][0]["causalTrials"] >= 30


def test_premature_forecast_detected():
    s = fixture(1, emit=False)
    s["events"].append({"seq": 2, "receivedAt": 120, "kind": "FORECAST",
                        "id": "early", "modelVersion": MODEL, "horizon": 1,
                        "probability": .5, "baseStart": 60})
    s["sequence"] = 2
    rebuild(s)
    r = audit(s)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["insufficientTrainingIssuanceCount"] == 1
    assert r["probabilityMismatchCount"] == 0


def test_other_model_is_not_attributed_to_frozen_issuer():
    r = audit(fixture(model="unrelated-model-v1"))
    assert r["status"] == "NO_MATCHING_MODEL_ISSUANCES"
    assert r["otherModelIssuancesNotEvaluated"] > 0
    assert r["recordedModelIssuances"] == 0


def test_unissued_eligible_opportunities_are_not_proven_missing():
    r = audit(fixture(45, emit="last"))
    assert r["status"] == "DECLARED_CAUSAL_REPLAY_MATCH_UNVERIFIED"
    assert r["recordedModelIssuances"] == 1
    assert r["unissuedEligibleOpportunitiesNotProvenMissing"] > 0


def test_gap_is_not_misread_as_training_continuity():
    r = audit(fixture(60, gap_at=25))
    assert r["probabilityMismatchCount"] == 0
    assert r["status"] == "DECLARED_CAUSAL_REPLAY_MATCH_UNVERIFIED"


def test_forged_outcome_fails_replay_equality():
    s = fixture()
    row = next(f for f in s["forecasts"] if f["status"] == "SETTLED")
    row["outcomeUp"] = not row["outcomeUp"]
    with pytest.raises(ValueError):
        audit(s)


def test_future_or_early_candle_fails_closed():
    s = fixture()
    s["events"][0]["receivedAt"] = 119
    with pytest.raises(ValueError):
        audit(s)


@pytest.mark.parametrize("bad", [True, 29, 1001, 30.0, None, "30"])
def test_invalid_training_minimum_rejected(bad):
    with pytest.raises(ValueError):
        audit(fixture(), min_samples=bad)


def test_empty_valid_journal_never_claims_success():
    s = fixture(0)
    r = audit(s)
    assert r["status"] == "NO_MATCHING_MODEL_ISSUANCES"
    assert r["recordedModelIssuances"] == 0
    assert r["eligibleCandleHorizonOpportunitiesDeclared"] == 0


def test_forecast_issuance_with_wrong_frozen_minimum_is_not_relabelled():
    r = audit(fixture(), min_samples=31)
    assert r["status"] == "NO_MATCHING_MODEL_ISSUANCES"
    assert r["otherModelIssuancesNotEvaluated"] > 0
