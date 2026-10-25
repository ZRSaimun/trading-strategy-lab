"""Synthetic-only causal challenger tests. No market feed or profitability claim."""
import copy
import math

import pytest

from app.forecast_decay_challenger import (
    CausalDecayChallenger, MODEL_VERSION, decayed_training,
)

IDENTITY = {"instrument": "SYNTH", "provider": "TEST", "venue": "TEST",
            "sourceId": "synthetic", "priceSide": "bid", "seconds": 60}


def candles(count=381, *, gap=None, up=True):
    return [{"kind": "CANDLE", "start": i * 60,
             "close": float(100 + i if up else 1000 - i)}
            for i in range(count) if i != gap]


class FakeStore:
    def __init__(self, rows):
        self.snapshot = {"sequence": len(rows), "identity": copy.deepcopy(IDENTITY),
                         "maxLagSeconds": 120, "events": copy.deepcopy(rows),
                         "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}
        self.conflict = False
        self.calls = 0

    def load(self, session_id):
        return copy.deepcopy(self.snapshot)

    def append_forecasts_atomic(self, session_id, identity, lag, expected, actions):
        self.calls += 1
        if self.conflict:
            return False
        assert expected == self.snapshot["sequence"]
        assert len({a["horizon"] for a in actions}) == len(actions)
        assert len({a["baseStart"] for a in actions}) == 1
        self.snapshot["events"].extend(copy.deepcopy(actions))
        self.snapshot["sequence"] += len(actions)
        return True


def test_disjoint_samples_and_frozen_decay():
    rows = candles(381)
    assert decayed_training(rows, 60, 1)[1] == 380
    assert decayed_training(rows, 60, 3)[1] == 126
    assert decayed_training(rows, 60, 12)[1] == 31
    assert all(0 < decayed_training(rows, 60, h)[0] < 1 for h in (1, 3, 12))
    assert all(decayed_training(rows, 60, h)[2] <= decayed_training(rows, 60, h)[1]
               for h in (1, 3, 12))


def test_no_future_target_training():
    rows = candles(25)
    p, n, _ = decayed_training(rows, 60, 12)
    assert n == 2  # bases 0 and 12; base 24 has no target yet
    assert 0 < p < 1
    assert decayed_training(rows[:12], 60, 12) == (None, 0, 0.0)


def test_gap_blocks_labels_spanning_it():
    full = candles(37)
    missing = candles(37, gap=12)
    assert decayed_training(full, 60, 12)[1] == 3
    assert decayed_training(missing, 60, 12)[1] == 1
    assert decayed_training(missing, 60, 1)[1] == 34


def test_monotonic_up_and_down_are_smoothed():
    up = decayed_training(candles(381), 60, 12)[0]
    down = decayed_training(candles(381, up=False), 60, 12)[0]
    assert 0 < down < 0.5 < up < 1
    assert math.isclose(up + down, 1.0, abs_tol=1e-12)


def test_no_forecast_until_frozen_minimum():
    store = FakeStore(candles(30))
    result = CausalDecayChallenger(store, "session", IDENTITY, 120).issue_for_latest(29 * 60)
    assert result["probabilities"] == {}
    assert store.calls == 0
    assert result["ordersSubmitted"] == 0 and result["live"] is False


def test_atomic_multi_horizon_and_restart_idempotence():
    store = FakeStore(candles(381))
    issuer = CausalDecayChallenger(store, "session", IDENTITY, 120)
    first = issuer.issue_for_latest(380 * 60)
    assert set(first["probabilities"]) == {1, 3, 12}
    assert store.calls == 1
    assert {e["horizon"] for e in store.snapshot["events"] if e["kind"] == "FORECAST"} == {1, 3, 12}
    second = issuer.issue_for_latest(380 * 60)
    assert second["sequence"] == first["sequence"]
    assert second["probabilities"] == first["probabilities"]
    assert store.calls == 1
    assert all(e["modelVersion"] == MODEL_VERSION for e in store.snapshot["events"] if e["kind"] == "FORECAST")


def test_cas_conflict_fails_closed():
    store = FakeStore(candles(381))
    store.conflict = True
    with pytest.raises(RuntimeError, match="CAS conflict"):
        CausalDecayChallenger(store, "session", IDENTITY, 120).issue_for_latest(380 * 60)
    assert store.snapshot["sequence"] == 381


def test_refuses_nonlatest_base():
    store = FakeStore(candles(381))
    with pytest.raises(ValueError, match="latest"):
        CausalDecayChallenger(store, "session", IDENTITY, 120).issue_for_latest(379 * 60)


def test_refuses_mismatched_source_or_lag():
    store = FakeStore(candles(381))
    with pytest.raises(ValueError, match="mismatched"):
        CausalDecayChallenger(store, "session", {**IDENTITY, "provider": "OTHER"}, 120).issue_for_latest(380 * 60)
    with pytest.raises(ValueError, match="mismatched"):
        CausalDecayChallenger(store, "session", IDENTITY, 0).issue_for_latest(380 * 60)


def test_refuses_model_rewrite_after_restart():
    store = FakeStore(candles(381))
    issuer = CausalDecayChallenger(store, "session", IDENTITY, 120)
    issuer.issue_for_latest(380 * 60)
    store.snapshot["events"][-1]["probability"] = 0.123
    with pytest.raises(ValueError, match="restart/model mismatch"):
        issuer.issue_for_latest(380 * 60)


def test_does_not_overwrite_baseline_model():
    rows = candles(381)
    rows.append({"kind": "FORECAST", "modelVersion": "jeffreys-utc-phase-v1-n30",
                 "baseStart": 380 * 60, "horizon": 1, "id": "baseline", "probability": 0.4})
    store = FakeStore(rows)
    CausalDecayChallenger(store, "session", IDENTITY, 120).issue_for_latest(380 * 60)
    assert any(e.get("id") == "baseline" and e["probability"] == 0.4 for e in store.snapshot["events"])


@pytest.mark.parametrize("bad", [True, 60.0, -60, 61])
def test_bad_candle_start(bad):
    rows = candles(2)
    rows[1]["start"] = bad
    with pytest.raises(ValueError, match="Invalid or revised"):
        decayed_training(rows, 60, 1)


@pytest.mark.parametrize("bad", [True, 0, -1, float("nan"), float("inf")])
def test_bad_candle_close(bad):
    rows = candles(2)
    rows[1]["close"] = bad
    with pytest.raises(ValueError, match="Invalid or revised"):
        decayed_training(rows, 60, 1)


@pytest.mark.parametrize("bad", [True, 0, 3.0, 13])
def test_bad_horizon(bad):
    with pytest.raises(ValueError, match="Invalid challenger horizon"):
        decayed_training(candles(20), 60, bad)


def test_ignores_partial_forecast_without_reissuing():
    store = FakeStore(candles(381))
    issuer = CausalDecayChallenger(store, "session", IDENTITY, 120)
    issuer.issue_for_latest(380 * 60)
    first = store.snapshot["events"]
    store.snapshot["events"] = [e for e in first if e.get("horizon") != 12]
    store.snapshot["sequence"] = len(store.snapshot["events"])
    issuer.issue_for_latest(380 * 60)
    assert store.calls == 2
    assert sum(e.get("horizon") == 12 for e in store.snapshot["events"]) == 1
