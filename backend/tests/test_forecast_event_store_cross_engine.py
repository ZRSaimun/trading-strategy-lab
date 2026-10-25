"""Disconnected forecast-journal cross-engine recovery acceptance.

SQLite checks run in normal CI. PostgreSQL concurrency is opt-in and accepts
ONLY a local test_ database with an isolated disposable randomized schema.
Never pass production credentials. No provider, broker, or network market feed.
"""
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base, Record
from app.forecast_event_store import ForecastEventStore

FEED = {
    "instrument": "XAUUSD-SYNTH",
    "provider": "SYNTHETIC",
    "venue": "TEST",
    "sourceId": "cross-engine-isolation",
    "priceSide": "bid",
    "seconds": 60,
}
SESSION_ID = "cross-engine-test"


def candle(start, close):
    return {"kind": "CANDLE", "start": start, "close": close}


def forecast(fid):
    return {
        "kind": "FORECAST", "id": fid, "modelVersion": "baseline",
        "horizon": 1, "probability": 0.7, "baseStart": 60,
    }


def append(store, sequence, action):
    return store.append(SESSION_ID, FEED, 120, sequence, action)


def audit_rows(factory):
    with factory() as db:
        return db.scalars(
            select(Audit).where(Audit.action == "forecast.events.append")
            .order_by(Audit.id)
        ).all()


def test_two_independent_sqlite_engines_restart_stale_retry_and_atomic_rollback(tmp_path):
    """Normal-CI check: independent connections share only durable DB state."""
    url = "sqlite:///" + str(tmp_path / "forecast-cross-engine.db")
    engines = [
        create_engine(url, connect_args={"timeout": 5}),
        create_engine(url, connect_args={"timeout": 5}),
    ]
    try:
        Base.metadata.create_all(engines[0])
        factories = [sessionmaker(engine) for engine in engines]
        clock = [120]
        a = ForecastEventStore(factories[0], lambda: clock[0])
        b = ForecastEventStore(factories[1], lambda: clock[0])
        assert append(a, 0, candle(60, 100))
        assert b.load(SESSION_ID)["sequence"] == 1
        assert append(b, 1, forecast("one"))
        assert append(a, 1, forecast("stale")) is False
        assert a.load(SESSION_ID)["sequence"] == 2
        assert len(audit_rows(factories[0])) == 2

        clock[0] = 180

        @event.listens_for(engines[1], "before_cursor_execute")
        def interrupt_audit(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
                raise RuntimeError("synthetic interrupted audit")

        try:
            with pytest.raises(RuntimeError, match="interrupted audit"):
                append(b, 2, candle(120, 103))
        finally:
            event.remove(engines[1], "before_cursor_execute", interrupt_audit)

        assert a.load(SESSION_ID)["sequence"] == 2
        assert len(audit_rows(factories[0])) == 2
        assert append(a, 2, candle(120, 103))
        recovered = ForecastEventStore(factories[1], lambda: clock[0]).load(SESSION_ID)
        assert recovered["sequence"] == 3
        assert recovered["forecasts"][0]["status"] == "SETTLED"
        assert recovered["forecasts"][0]["outcomeUp"] is True
        assert len(audit_rows(factories[1])) == 3
    finally:
        for engine in engines:
            engine.dispose()


def test_postgres_independent_engines_same_expected_sequence_one_winner():
    """Optional LOCAL PostgreSQL acceptance, not proof of a real crash or feed."""
    raw = os.getenv("FORECAST_JOURNAL_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Set FORECAST_JOURNAL_TEST_DATABASE_URL for isolated local PostgreSQL acceptance")
    try:
        url = make_url(raw)
    except Exception as exc:
        pytest.fail("Invalid PostgreSQL test URL: " + type(exc).__name__)
    if (url.get_backend_name() != "postgresql"
            or url.host not in ("localhost", "127.0.0.1", "db")
            or not (url.database or "").startswith("test_")
            or url.query):
        pytest.fail("Refusing non-local, non-test_, or parameterized PostgreSQL URL")

    schema = "test_forecast_" + uuid.uuid4().hex
    engines = []
    created = False
    try:
        first = create_engine(url, pool_size=2, max_overflow=0,
                              connect_args={"connect_timeout": 3})
        engines.append(first)
        with first.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        second = create_engine(url, pool_size=2, max_overflow=0,
                               connect_args={"connect_timeout": 3})
        engines.append(second)

        for engine in engines:
            @event.listens_for(engine, "begin")
            def isolated_transaction(conn):
                conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                conn.exec_driver_sql("SET LOCAL statement_timeout TO '10s'")

        Base.metadata.create_all(first)
        factories = [sessionmaker(engine) for engine in engines]
        a = ForecastEventStore(factories[0], lambda: 120)
        b = ForecastEventStore(factories[1], lambda: 120)
        assert append(a, 0, candle(60, 100))
        barrier = threading.Barrier(2, timeout=7)

        def synchronized_read(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT RECORDS.VALUE"):
                barrier.wait()

        for engine in engines:
            event.listen(engine, "after_cursor_execute", synchronized_read)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(append, a, 1, forecast("writer-a")),
                    pool.submit(append, b, 1, forecast("writer-b")),
                ]
                outcomes = [future.result(timeout=15) for future in futures]
        finally:
            for engine in engines:
                event.remove(engine, "after_cursor_execute", synchronized_read)

        assert sorted(outcomes) == [False, True]
        observed = b.load(SESSION_ID)
        assert observed["sequence"] == 2
        assert observed["forecasts"][0]["id"] in ("writer-a", "writer-b")
        assert len(audit_rows(factories[0])) == 2

        @event.listens_for(engines[1], "before_cursor_execute")
        def interrupt_audit(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
                raise RuntimeError("synthetic interrupted audit")

        try:
            with pytest.raises(RuntimeError, match="interrupted audit"):
                append(b, 2, candle(120, 103))
        finally:
            event.remove(engines[1], "before_cursor_execute", interrupt_audit)
        assert a.load(SESSION_ID)["sequence"] == 2
        assert len(audit_rows(factories[0])) == 2
        assert ForecastEventStore(factories[0], lambda: 180).append(
            SESSION_ID, FEED, 120, 2, candle(120, 103))
        assert ForecastEventStore(factories[1], lambda: 180).load(
            SESSION_ID)["forecasts"][0]["status"] == "SETTLED"
        assert len(audit_rows(factories[0])) == 3
    finally:
        if created:
            # Only this test's randomized schema. Never touch public/owner tables.
            try:
                with engines[0].begin() as conn:
                    conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                for engine in engines:
                    engine.dispose()
        else:
            for engine in engines:
                engine.dispose()
