"""Synthetic offline tests; no provider receipts or demonstrated market edge."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.forecast_event_store import ForecastEventStore
from app.forecast_causal_issuer import CausalForecastIssuer, _training, MODEL_VERSION

FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC", "venue": "TEST",
        "sourceId": "issuer-test", "priceSide": "bid", "seconds": 60}


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "issuer.db"))
    Base.metadata.create_all(engine)
    clock = [120]
    factory = sessionmaker(engine)
    store = ForecastEventStore(factory, lambda: clock[0])
    yield CausalForecastIssuer(store, "issuer-1", FEED, 120, min_samples=30), clock, factory
    engine.dispose()


def _feed_rows(issuer, clock, count, issue=True):
    for index in range(1, count + 1):
        start = index * 60
        clock[0] = start + 60
        if issue:
            issuer.accept(start, 100 + (index % 7))
        else:
            current = issuer.store.load("issuer-1")
            assert issuer.store.append("issuer-1", FEED, 120,
                                       current["sequence"] if current else 0,
                                       {"kind": "CANDLE", "start": start,
                                        "close": 100 + (index % 7)})


def test_fixed_phase_training_never_crosses_gap():
    rows = [{"start": 0, "close": 1}, {"start": 60, "close": 2},
            {"start": 180, "close": 4}, {"start": 240, "close": 5}]
    assert _training(rows, 60, 1) == (2, 2)
    assert _training(rows, 60, 3) == (0, 0)


def test_nonoverlapping_horizon_samples():
    rows = [{"start": i * 60, "close": float(i + 1)} for i in range(40)]
    assert _training(rows, 60, 1) == (39, 39)
    assert _training(rows, 60, 3) == (13, 13)
    assert _training(rows, 60, 12) == (3, 3)


def test_minimum_history_and_recovery_idempotence(env):
    issuer, clock, _ = env
    _feed_rows(issuer, clock, 30)
    result = issuer.store.load("issuer-1")
    assert not result["forecasts"]
    clock[0] = 31 * 60 + 60
    first = issuer.accept(31 * 60, 102)
    assert first["probabilities"].keys() == {1}
    assert 0 < first["probabilities"][1] < 1
    seq = first["sequence"]
    again = issuer.accept(31 * 60, 102)
    assert again["sequence"] == seq
    assert again["probabilities"] == first["probabilities"]
    assert again["live"] is False and again["ordersSubmitted"] == 0


def test_all_horizons_after_enough_prospective_observations(env):
    issuer, clock, _ = env
    _feed_rows(issuer, clock, 379, issue=False)
    clock[0] = 380 * 60 + 60
    issuer.accept(380 * 60, 102)
    snapshot = issuer.store.load("issuer-1")
    forecasts = snapshot["forecasts"]
    assert {f["horizon"] for f in forecasts} == {1, 3, 12}
    assert all(f["modelVersion"] == issuer.model_version for f in forecasts)
    assert all(0 < f["probability"] < 1 for f in forecasts)
    assert all(f["issuedAt"] >= f["baseStart"] + 60 for f in forecasts)


def test_source_and_revision_rejection(env):
    issuer, clock, _ = env
    issuer.accept(60, 101)
    with pytest.raises(ValueError, match="revised"):
        issuer.accept(60, 102)
    with pytest.raises(ValueError, match="Backward"):
        issuer.accept(0, 101)
    different = CausalForecastIssuer(issuer.store, "issuer-1", {**FEED, "provider": "OTHER"}, 120)
    with pytest.raises(ValueError, match="source"):
        different.accept(60, 101)


@pytest.mark.parametrize("bad", [0, -1, 29, 1001, True, 30.0])
def test_invalid_minimum_samples(bad, env):
    issuer, _, _ = env
    with pytest.raises(ValueError, match="min_samples"):
        CausalForecastIssuer(issuer.store, "issuer-1", FEED, 120, bad)


@pytest.mark.parametrize("start,close", [(True, 1), (-60, 1), (60, 0), (60, True), (60, float("nan")), (60, float("inf"))])
def test_invalid_observation(start, close, env):
    issuer, _, _ = env
    with pytest.raises(ValueError, match="Invalid"):
        issuer.accept(start, close)


def test_no_retroactive_recovery_after_deadline(env):
    issuer, clock, factory = env
    _feed_rows(issuer, clock, 30)
    # Candle persisted by a crashed worker; forecast was not yet appended.
    clock[0] = 31 * 60 + 60
    assert issuer.store.append("issuer-1", FEED, 120, issuer.store.load("issuer-1")["sequence"],
                               {"kind": "CANDLE", "start": 31 * 60, "close": 102})
    clock[0] = 33 * 60 + 60
    with pytest.raises(ValueError, match="Retroactive"):
        issuer.accept(31 * 60, 102)
    assert issuer.store.load("issuer-1")["forecasts"] == []


def test_partial_issuance_crash_recover_within_window(env):
    issuer, clock, _ = env
    _feed_rows(issuer, clock, 380, issue=False)
    start = 381 * 60
    clock[0] = start + 60
    assert issuer.store.append("issuer-1", FEED, 120, issuer.store.load("issuer-1")["sequence"],
                               {"kind": "CANDLE", "start": start, "close": 101})
    prior = issuer.store.load("issuer-1")
    result = issuer.accept(start, 101)
    assert result["sequence"] == prior["sequence"] + 3
    assert issuer.accept(start, 101)["sequence"] == result["sequence"]
