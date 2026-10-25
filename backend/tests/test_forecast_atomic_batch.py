"""Synthetic disconnected forecast batch regression tests."""
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.db import Base, Audit
from app.forecast_event_store import ForecastEventStore
from app.forecast_causal_issuer import CausalForecastIssuer

FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC", "venue": "TEST",
        "sourceId": "batch", "priceSide": "bid", "seconds": 60}
SESSION = "atomic-test"


@pytest.fixture
def state(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "batch.db"))
    Base.metadata.create_all(engine)
    clock = [120]
    factory = sessionmaker(engine)
    store = ForecastEventStore(factory, lambda: clock[0])
    yield store, factory, engine, clock
    engine.dispose()


def forecast(horizon, model="baseline", base=60):
    return {"kind": "FORECAST", "id": "f" + str(horizon),
            "modelVersion": model, "horizon": horizon,
            "probability": .65, "baseStart": base}


def seeded(state):
    store = state[0]
    assert store.append(SESSION, FEED, 120, 0, {"kind": "CANDLE", "start": 60, "close": 100})
    return store


def batch(store, seq=1, actions=None):
    if actions is None:
        actions = [forecast(1), forecast(3), forecast(12)]
    return store.append_forecasts_atomic(SESSION, FEED, 120, seq, actions)


def audits(factory):
    with factory() as db:
        return db.scalars(select(Audit).order_by(Audit.id)).all()


def test_all_horizons_and_audits_are_one_transaction(state):
    store, factory, _, _ = state
    seeded(state)
    assert batch(store)
    assert store.load(SESSION)["sequence"] == 4
    assert {f["horizon"] for f in store.load(SESSION)["forecasts"]} == {1, 3, 12}
    assert len(audits(factory)) == 4


def test_stale_cas_cannot_publish_any_horizon(state):
    store, factory, _, _ = state
    seeded(state)
    assert batch(store)
    assert batch(store) is False
    assert store.load(SESSION)["sequence"] == 4
    assert len(audits(factory)) == 4


@pytest.mark.parametrize("actions", [
    [], [forecast(1), forecast(1)],
    [forecast(1), forecast(3, model="other")],
    [forecast(1), forecast(3, base=120)],
    [{"kind": "CANDLE", "start": 60, "close": 101}],
    [{**forecast(1), "receivedAt": 120}],
])
def test_invalid_batch_is_rejected_without_mutation(state, actions):
    store, factory, _, _ = state
    seeded(state)
    with pytest.raises(ValueError):
        batch(store, actions=actions)
    assert store.load(SESSION)["sequence"] == 1
    assert len(audits(factory)) == 1


def test_failed_audit_insert_rolls_back_every_horizon(state):
    store, factory, engine, _ = state
    seeded(state)
    @event.listens_for(engine, "before_cursor_execute")
    def crash(_conn, _cursor, statement, _params, _ctx, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic crash")
    try:
        with pytest.raises(RuntimeError, match="synthetic crash"):
            batch(store)
    finally:
        event.remove(engine, "before_cursor_execute", crash)
    assert store.load(SESSION)["sequence"] == 1
    assert len(audits(factory)) == 1
    assert batch(store)


def test_late_batch_cannot_backdate_forecasts(state):
    store, factory, _, clock = state
    seeded(state)
    clock[0] = 181
    with pytest.raises(ValueError, match="Retroactive"):
        batch(store)
    assert store.load(SESSION)["sequence"] == 1
    assert len(audits(factory)) == 1


def test_issuer_publishes_three_horizons_atomically_and_retry_is_idempotent(state):
    store, factory, _, clock = state
    issuer = CausalForecastIssuer(store, SESSION, FEED, 120, min_samples=30)
    for index in range(1, 380):
        start = index * 60
        clock[0] = start + 60
        snapshot = store.load(SESSION)
        assert store.append(SESSION, FEED, 120, snapshot["sequence"] if snapshot else 0,
                            {"kind": "CANDLE", "start": start, "close": 100 + index % 7})
    clock[0] = 380 * 60 + 60
    before = store.load(SESSION)["sequence"]
    result = issuer.accept(380 * 60, 102)
    assert result["sequence"] == before + 4
    assert set(result["probabilities"]) == {1, 3, 12}
    assert issuer.accept(380 * 60, 102)["sequence"] == result["sequence"]
    assert len(audits(factory)) == result["sequence"]


def test_batch_refuses_mixed_feed(state):
    store, factory, _, _ = state
    seeded(state)
    with pytest.raises(ValueError, match="identity mismatch"):
        store.append_forecasts_atomic(
            SESSION, {**FEED, "provider": "OTHER"}, 120, 1, [forecast(1)])
    assert store.load(SESSION)["sequence"] == 1
    assert len(audits(factory)) == 1
