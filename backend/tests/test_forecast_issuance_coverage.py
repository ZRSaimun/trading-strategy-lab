"""Synthetic issuance-census tests; no live prices, alerts or orders."""
from copy import deepcopy
import pytest

from app.forecast_issuance_coverage import audit_forecast_issuance_coverage as audit

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "issuance-test", "priceSide": "bid", "seconds": 60}


def fixture(keys=(("model-a", 1, 60), ("model-a", 3, 120), ("model-b", 12, 180))):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(keys):
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": .6,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": .6, "baseStart": base, "baseClose": 100.0,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": 60, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def test_exact_declared_match_is_not_independent_authentication():
    keys = [("model-a", 1, 60), ("model-a", 3, 120), ("model-b", 12, 180)]
    s = fixture(keys)
    before = deepcopy((s, keys))
    r = audit(s, IDENTITY, keys, as_of=240)
    assert (s, keys) == before
    assert r["status"] == "DECLARED_MATCH_UNVERIFIED"
    assert r["expectedCount"] == r["observedCount"] == 3
    assert r["missingCount"] == r["unexpectedCount"] == 0
    assert all(r[k] is False for k in ("sourceAuthenticated", "scheduleIndependentlyVerified",
        "forecastDeliveryVerified", "maySendNotification", "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_missing_and_unexpected_are_both_visible_without_silent_backfill():
    s = fixture()
    expected = [("model-a", 1, 60), ("model-a", 3, 120), ("model-c", 1, 240)]
    r = audit(s, IDENTITY, expected, as_of=300)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["missingCount"] == r["unexpectedCount"] == 1
    assert r["missingKeysFirst50"] == [["model-c", 1, 240]]
    assert r["unexpectedKeysFirst50"] == [["model-b", 12, 180]]


def test_empty_declared_register_is_not_proof_of_completeness():
    r = audit(fixture([]), IDENTITY, [], as_of=300)
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["scheduleIndependentlyVerified"] is False


def test_duplicate_observed_model_horizon_base_fails_closed():
    s = fixture([("model-a", 1, 60), ("model-a", 1, 60)])
    with pytest.raises(ValueError, match="Duplicate observed"):
        audit(s, IDENTITY, [("model-a", 1, 60)], as_of=300)


@pytest.mark.parametrize("bad", [
    [("model-a", 1, 60), ("model-a", 1, 60)],
    [("model-a", True, 60)],
    [("model-a", 2, 60)],
    [("model-a", 1, 61)],
    [("model-a", 1, 300)],
    [("model-a", 1, -60)],
    [("model\nspoof", 1, 60)],
    [["model-a", 1]],
    ["bad"],
    {},
    None,
])
def test_invalid_register_fails_closed(bad):
    with pytest.raises(ValueError):
        audit(fixture(), IDENTITY, bad, as_of=300)


@pytest.mark.parametrize("bad", [True, -1, 1.5, 2**53])
def test_invalid_cutoff_fails_closed(bad):
    with pytest.raises(ValueError, match="cutoff"):
        audit(fixture(), IDENTITY, [], as_of=bad)


def test_future_issuance_rejected_even_if_expected_schedule_is_empty():
    with pytest.raises(ValueError, match="future observed"):
        audit(fixture(), IDENTITY, [], as_of=180)


def test_mismatched_identity_and_forged_source_fail_closed():
    with pytest.raises(ValueError, match="identity mismatch"):
        audit(fixture(), {**IDENTITY, "priceSide": "ask"}, [], as_of=300)
    s = fixture()
    s["evidence"] = "AUTHENTICATED_LIVE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, [], as_of=300)


def test_outcome_not_required_for_issuance_coverage():
    s = fixture()
    assert all(r["status"] == "PENDING" for r in s["forecasts"])
    r = audit(s, IDENTITY, [(r["modelVersion"], r["horizon"], r["baseStart"])
                            for r in s["forecasts"]], as_of=300)
    assert r["status"] == "DECLARED_MATCH_UNVERIFIED"
    assert not r["forecastDeliveryVerified"]


def test_50_key_output_cap_does_not_hide_full_missing_count():
    expected = [("model-a", 1, i * 60) for i in range(1, 102)]
    r = audit(fixture([]), IDENTITY, expected, as_of=7000)
    assert r["missingCount"] == 101
    assert len(r["missingKeysFirst50"]) == 50
    assert r["truncatedKeyLists"]
