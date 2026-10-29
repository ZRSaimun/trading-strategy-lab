"""Synthetic declared decision population tests: no market or broker access."""
from copy import deepcopy
import pytest

from app.forecast_decision_coverage import audit_forecast_decision_coverage as audit

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "decision-test", "priceSide": "bid", "seconds": 60}
KEYS = [("m1", 1, 60), ("m1", 3, 120), ("m2", 12, 180)]


def snapshot(keys=KEYS, lag=30):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(keys):
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": .6,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": .6, "baseStart": base, "baseClose": 100.,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": lag, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def abstain(key, *, at=None, reason="LOW_CONFIDENCE"):
    model, horizon, base = key
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60 if at is None else at, "reason": reason}


def test_forecasts_only_match_but_are_not_authenticated():
    s = snapshot()
    before = deepcopy(s)
    r = audit(s, IDENTITY, KEYS, [], as_of=300)
    assert s == before
    assert r["status"] == "DECLARED_DECISIONS_MATCH_UNVERIFIED"
    assert r["coveredExactlyOnceCount"] == 3
    assert r["declaredAbstentionRate"] == 0
    assert all(r[k] is False for k in ("sourceAuthenticated", "scheduleIndependentlyVerified",
        "abstentionsIndependentlyVerified", "forecastDeliveryVerified", "maySendNotification",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_explicit_abstention_counts_as_declared_decision_not_forecast():
    s = snapshot(KEYS[:2])
    r = audit(s, IDENTITY, KEYS, [abstain(KEYS[2])], as_of=300)
    assert r["status"] == "DECLARED_DECISIONS_MATCH_UNVERIFIED"
    assert (r["forecastCount"], r["abstentionCount"], r["coveredExactlyOnceCount"]) == (2, 1, 3)
    assert r["declaredAbstentionRate"] == pytest.approx(1/3)
    assert r["declaredValidAbstentionsByReason"]["LOW_CONFIDENCE"] == 1


def test_missing_decision_not_silently_backfilled():
    r = audit(snapshot(KEYS[:2]), IDENTITY, KEYS, [], as_of=300)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["missingDecisionCount"] == 1
    assert r["missingKeysFirst50"] == [list(KEYS[2])]


def test_forecast_and_abstention_conflict_not_counted_twice():
    r = audit(snapshot(), IDENTITY, KEYS, [abstain(KEYS[0])], as_of=300)
    assert r["conflictingDecisionCount"] == 1
    assert r["coveredExactlyOnceCount"] == 2
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["declaredAbstentionRate"] == 0


def test_unexpected_forecast_and_abstention_reported_separately():
    other = ("m3", 1, 240)
    r = audit(snapshot([KEYS[0], other]), IDENTITY, [KEYS[0]],
              [abstain(KEYS[2])], as_of=360)
    assert r["unexpectedForecastCount"] == 1
    assert r["unexpectedAbstentionCount"] == 1
    assert r["coveredExactlyOnceCount"] == 1


def test_empty_schedule_cannot_certify_coverage():
    r = audit(snapshot([]), IDENTITY, [], [], as_of=300)
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["declaredAbstentionRate"] is None


@pytest.mark.parametrize("bad", [
    {"modelVersion": "m2", "horizon": 12, "baseStart": 180, "decisionAt": 240},
    {"modelVersion": "m2", "horizon": 12, "baseStart": 180, "decisionAt": 240, "reason": "OTHER", "auth": True},
    {"modelVersion": "m2", "horizon": 12, "baseStart": 180, "decisionAt": True, "reason": "OTHER"},
    abstain(KEYS[2], at=239), abstain(KEYS[2], at=271),
    abstain(KEYS[2], at=300), abstain(KEYS[2], at=240, reason="SENT"),
    abstain(("m2", True, 180)), abstain(("m2", 12, 181)),
    abstain(("m\nspoof", 12, 180)), abstain(("m2", 12, 300)),
])
def test_malformed_abstentions_fail_closed(bad):
    with pytest.raises(ValueError):
        audit(snapshot([]), IDENTITY, KEYS, [bad], as_of=300)


@pytest.mark.parametrize("bad", [None, {}, "abstain", [abstain(KEYS[2])] * 5001])
def test_invalid_abstention_container_fails_closed(bad):
    with pytest.raises(ValueError):
        audit(snapshot([]), IDENTITY, KEYS, bad, as_of=300)


def test_duplicate_abstention_fails_closed():
    with pytest.raises(ValueError, match="Duplicate"):
        audit(snapshot([]), IDENTITY, KEYS, [abstain(KEYS[2]), abstain(KEYS[2])], as_of=300)


def test_declared_abstention_cannot_hide_forged_source():
    s = snapshot([])
    s["evidence"] = "AUTHENTICATED_LIVE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, KEYS, [abstain(KEYS[2])], as_of=300)


def test_declared_abstention_cannot_hide_identity_mismatch():
    with pytest.raises(ValueError):
        audit(snapshot([]), {**IDENTITY, "priceSide": "ask"}, KEYS,
              [abstain(KEYS[2])], as_of=300)


def test_output_caps_are_not_count_caps():
    expected = [("m1", 1, i*60) for i in range(1, 102)]
    r = audit(snapshot([]), IDENTITY, expected, [], as_of=7000)
    assert r["missingDecisionCount"] == 101
    assert len(r["missingKeysFirst50"]) == 50
    assert r["truncatedKeyLists"]


def test_exact_max_lag_boundary_accepted():
    r = audit(snapshot([]), IDENTITY, [KEYS[2]],
              [abstain(KEYS[2], at=270)], as_of=300)
    assert r["status"] == "DECLARED_DECISIONS_MATCH_UNVERIFIED"


def test_reason_counts_are_exclusive_and_sorted():
    s = snapshot([])
    a = [abstain(KEYS[0], reason="OTHER"),
         abstain(KEYS[1], reason="DATA_QUALITY"),
         abstain(KEYS[2], reason="OTHER")]
    r = audit(s, IDENTITY, KEYS, a, as_of=300)
    assert r["declaredValidAbstentionsByReason"]["OTHER"] == 2
    assert r["declaredValidAbstentionsByReason"]["DATA_QUALITY"] == 1
    assert r["coveredExactlyOnceCount"] == 3
