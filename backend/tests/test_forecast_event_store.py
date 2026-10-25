"""Isolated SQLite regression tests; synthetic prices are not market evidence."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, Record, Audit
from app.forecast_event_store import ForecastEventStore

FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC", "venue": "TEST",
        "sourceId": "isolated", "priceSide": "bid", "seconds": 60}


@pytest.fixture
def state(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "forecast.db"), connect_args={"timeout": 3})
    Base.metadata.create_all(engine)
    clock = [120]
    factory = sessionmaker(engine)
    store = ForecastEventStore(factory, lambda: clock[0])
    yield store, factory, engine, clock
    engine.dispose()


def candle(start, close):
    return {"kind": "CANDLE", "start": start, "close": close}


def forecast(fid, horizon=1, probability=.7, model="baseline"):
    return {"kind": "FORECAST", "id": fid, "modelVersion": model,
            "horizon": horizon, "probability": probability, "baseStart": 60}


def append(store, seq, action):
    return store.append("prospective-1", FEED, 120, seq, action)


def test_restart_replay_and_completed_target_settlement(state):
    store, factory, _, clock = state
    assert store.load("prospective-1") is None
    assert append(store, 0, candle(60, 100))
    assert append(store, 1, forecast("f1"))
    clock[0] = 180
    assert append(store, 2, candle(120, 102))
    again = ForecastEventStore(factory, lambda: clock[0]).load("prospective-1")
    assert again["sequence"] == 3
    assert again["evidence"] == "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"
    assert again["forecasts"][0]["status"] == "SETTLED"
    assert again["forecasts"][0]["outcomeUp"] is True
    assert again["forecasts"][0]["resolvedAt"] == 180
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "forecast.events.append")).all()) == 3


def test_horizon_three_and_twelve_only_settle_on_completed_target(state):
    store, _, _, clock = state
    assert append(store, 0, candle(60, 100))
    assert append(store, 1, forecast("f3", horizon=3))
    assert append(store, 2, forecast("f12", horizon=12))
    for seq, start in enumerate(range(120, 840, 60), start=3):
        clock[0] = start + 60
        assert append(store, seq, candle(start, 100 + start / 100))
    rows = {x["id"]: x for x in store.load("prospective-1")["forecasts"]}
    assert rows["f3"]["status"] == "SETTLED"
    assert rows["f12"]["status"] == "SETTLED"
    assert rows["f3"]["resolvedAt"] == 300
    assert rows["f12"]["resolvedAt"] == 840


def test_gap_voids_pending_without_false_fill(state):
    store, _, _, clock = state
    assert append(store, 0, candle(60, 100))
    assert append(store, 1, forecast("f1"))
    clock[0] = 240
    assert append(store, 2, candle(180, 200))
    row = store.load("prospective-1")["forecasts"][0]
    assert row["status"] == "VOID_GAP" and row["outcomeUp"] is None


def test_stale_writer_and_duplicate_retries_do_not_publish(state):
    store, factory, _, clock = state
    assert append(store, 0, candle(60, 100))
    assert not append(store, 0, candle(60, 100))
    assert append(store, 1, forecast("f1"))
    with pytest.raises(ValueError, match="duplicate"):
        append(store, 2, forecast("f1"))
    assert store.load("prospective-1")["sequence"] == 2
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "forecast.events.append")).all()) == 2


def test_conflicting_feed_and_invalid_clock_fail_closed(state):
    store, _, _, clock = state
    assert append(store, 0, candle(60, 100))
    with pytest.raises(ValueError, match="identity mismatch"):
        store.append("prospective-1", {**FEED, "provider": "other"}, 120, 1, forecast("f1"))
    clock[0] = -1
    with pytest.raises(ValueError, match="clock"):
        append(store, 1, forecast("f1"))


@pytest.mark.parametrize("bad", [
    {"kind": "CANDLE", "start": 60, "close": float("nan")},
    {"kind": "CANDLE", "start": 61, "close": 1},
    {"kind": "CANDLE", "start": 60, "close": 0},
    {"kind": "CANDLE", "start": 60, "close": 1, "receivedAt": 120},
    {"kind": "CANDLE", "start": 60, "close": 1, "seq": 1},
    {"kind": "FORECAST", "id": "f", "modelVersion": "m", "horizon": 1, "probability": .7, "baseStart": 60},
])
def test_rejects_invalid_initial_event(state, bad):
    store, _, _, _ = state
    with pytest.raises(ValueError):
        append(store, 0, bad)
    assert store.load("prospective-1") is None


def test_forecast_cannot_be_issued_after_next_bar_close(state):
    store, _, _, clock = state
    assert append(store, 0, candle(60, 100))
    clock[0] = 180
    with pytest.raises(ValueError, match="Retroactive"):
        append(store, 1, forecast("late"))


def test_rejects_future_and_stale_completed_candles(state):
    store, _, _, clock = state
    clock[0] = 119
    with pytest.raises(ValueError, match="Uncompleted"):
        append(store, 0, candle(60, 100))
    clock[0] = 241
    with pytest.raises(ValueError, match="stale"):
        append(store, 0, candle(60, 100))


def test_rejects_revisions_and_duplicate_model_bar_horizon(state):
    store, _, _, clock = state
    assert append(store, 0, candle(60, 100))
    assert append(store, 1, forecast("f1"))
    with pytest.raises(ValueError, match="Duplicate model"):
        append(store, 2, forecast("f2"))
    with pytest.raises(ValueError, match="Revised"):
        append(store, 2, candle(60, 101))


def test_atomic_audit_rollback_on_synthetic_crash(state):
    store, factory, engine, clock = state
    assert append(store, 0, candle(60, 100))
    @event.listens_for(engine, "before_cursor_execute")
    def crash(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("simulated audit failure")
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            append(store, 1, forecast("f1"))
    finally:
        event.remove(engine, "before_cursor_execute", crash)
    assert store.load("prospective-1")["sequence"] == 1
    assert append(store, 1, forecast("f1"))
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "forecast.events.append")).all()) == 2


def test_corrupt_payload_or_digest_never_replayed(state):
    store, factory, _, _ = state
    assert append(store, 0, candle(60, 100))
    key = store._key("prospective-1")
    with factory.begin() as db:
        record = db.get(Record, key)
        doc = json.loads(record.value)
        doc["payload"] = doc["payload"].replace('"close":100', '"close":999')
        record.value = json.dumps(doc)
    with pytest.raises(ValueError, match="corrupt"):
        store.load("prospective-1")
    with pytest.raises(ValueError, match="corrupt"):
        append(store, 1, forecast("f1"))


def test_invalid_append_bounds_and_unsupported_fields(state):
    store, _, _, _ = state
    with pytest.raises(ValueError, match="bounds"):
        store.append("prospective-1", FEED, 120, True, candle(60, 100))
    with pytest.raises(ValueError, match="bounds"):
        store.append("prospective-1", FEED, 3601, 0, candle(60, 100))
    with pytest.raises(ValueError, match="Malformed"):
        append(store, 0, {**candle(60, 100), "fakeExecutableAsk": 101})


def test_two_writers_one_atomic_winner(state):
    store, factory, engine, clock = state
    assert append(store, 0, candle(60, 100))
    def worker(fid):
        return ForecastEventStore(factory, lambda: 120).append(
            "prospective-1", FEED, 120, 1, forecast(fid))
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, ("one", "two")))
    assert sorted(outcomes) == [False, True]
    assert store.load("prospective-1")["sequence"] == 2
