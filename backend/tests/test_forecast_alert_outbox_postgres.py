"""Isolated PostgreSQL acceptance for the disconnected forecast alert outbox.

Opt-in. Refuses remote/non-test databases; creates and drops ONLY a random schema.
No notification provider, market feed, paper fill or broker is contacted.
"""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base
from app.forecast_event_store import ForecastEventStore
from app.forecast_alert_outbox import ForecastAlertOutbox

FEED = {
    "instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC",
    "venue": "TEST", "sourceId": "postgres-alert-acceptance",
    "priceSide": "bid", "seconds": 60,
}
FID = "one-step-prospective"


def _seed(factory, session_id):
    journal = ForecastEventStore(factory, lambda: 120)
    assert journal.append(
        session_id, FEED, 120, 0,
        {"kind": "CANDLE", "start": 60, "close": 100},
    )
    assert journal.append_forecasts_atomic(
        session_id, FEED, 120, 1, [{
            "kind": "FORECAST", "id": FID, "modelVersion": "test-only",
            "horizon": 1, "probability": 0.6, "baseStart": 60,
        }],
    )


def _count(factory, action):
    with factory() as db:
        return len(db.scalars(select(Audit).where(Audit.action == action)).all())


def test_postgres_two_worker_claim_recovery_and_audit_rollback():
    raw = os.getenv("FORECAST_ALERT_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Requires isolated local PostgreSQL test database")
    try:
        url = make_url(raw)
    except Exception as exc:
        pytest.fail("Invalid PostgreSQL acceptance URL: " + type(exc).__name__)
    if (url.get_backend_name() != "postgresql"
            or url.host not in ("127.0.0.1", "localhost", "db")
            or not (url.database or "").startswith("test_")
            or url.query):
        pytest.fail("Refusing remote, non-test or parameterized database URL")

    schema = "test_forecast_alert_" + uuid.uuid4().hex
    engines = []
    created = False
    try:
        first = create_engine(
            url, pool_size=2, max_overflow=0,
            connect_args={"connect_timeout": 3},
        )
        engines.append(first)
        with first.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        second = create_engine(
            url, pool_size=2, max_overflow=0,
            connect_args={"connect_timeout": 3},
        )
        engines.append(second)
        for engine in engines:
            @event.listens_for(engine, "begin")
            def isolated_transaction(conn):
                conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                conn.exec_driver_sql("SET LOCAL statement_timeout TO '10s'")

        Base.metadata.create_all(first)
        a_factory, b_factory = (sessionmaker(engine) for engine in engines)
        _seed(a_factory, "concurrent-claim")
        a = ForecastAlertOutbox(a_factory, lambda: 120)
        b = ForecastAlertOutbox(b_factory, lambda: 120)
        assert a.queue("concurrent-claim", FEED, FID)

        # Both workers observe the same QUEUED snapshot before their CAS.
        # PostgreSQL must allow exactly one claim and one audit record.
        barrier = threading.Barrier(2, timeout=7)
        def synchronize_reads(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT RECORDS.VALUE"):
                barrier.wait(timeout=7)

        for engine in engines:
            event.listen(engine, "after_cursor_execute", synchronize_reads)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(a.claim, "concurrent-claim", FID),
                    pool.submit(b.claim, "concurrent-claim", FID),
                ]
                results = [future.result(timeout=15) for future in futures]
        finally:
            for engine in engines:
                event.remove(engine, "after_cursor_execute", synchronize_reads)

        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        assert winners[0]["status"] == "IN_FLIGHT_UNCERTAIN"
        assert winners[0]["notificationEnabled"] is False
        assert winners[0]["mayExecuteLiveOrder"] is False
        assert _count(a_factory, "forecast.alert.claim") == 1
        assert b.read("concurrent-claim", FID)["claimId"] == winners[0]["claimId"]
        assert a.claim("concurrent-claim", FID) is None

        # A new instance after a hypothetical worker restart must NOT resend.
        restarted = ForecastAlertOutbox(b_factory, lambda: 120)
        assert restarted.claim("concurrent-claim", FID) is None
        assert restarted.queue("concurrent-claim", FEED, FID) is False
        assert restarted.acknowledge_unverified(
            "concurrent-claim", FID, "wrong-claim-id",
        ) is None
        acknowledged = restarted.acknowledge_unverified(
            "concurrent-claim", FID, winners[0]["claimId"],
        )
        assert acknowledged["status"] == "ACK_RECORDED_UNVERIFIED"
        assert acknowledged["deliveryVerified"] is False
        assert _count(b_factory, "forecast.alert.ack") == 1

        # A failure inserting audit must roll back the claim update too.
        _seed(a_factory, "rollback-claim")
        assert a.queue("rollback-claim", FEED, FID)
        @event.listens_for(engines[0], "before_cursor_execute")
        def fail_audit(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
                raise RuntimeError("synthetic PostgreSQL audit interruption")

        try:
            with pytest.raises(RuntimeError, match="audit interruption"):
                a.claim("rollback-claim", FID)
        finally:
            event.remove(engines[0], "before_cursor_execute", fail_audit)

        assert b.read("rollback-claim", FID)["status"] == "QUEUED"
        assert _count(b_factory, "forecast.alert.claim") == 1
        recovered = restarted.claim("rollback-claim", FID)
        assert recovered["status"] == "IN_FLIGHT_UNCERTAIN"
        assert _count(a_factory, "forecast.alert.claim") == 2
    finally:
        if created:
            try:
                with engines[0].begin() as conn:
                    conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                for engine in engines:
                    engine.dispose()
        else:
            for engine in engines:
                engine.dispose()
