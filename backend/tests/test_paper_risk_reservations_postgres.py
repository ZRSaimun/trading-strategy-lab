"""Opt-in PostgreSQL CAS acceptance for PAPER risk reservations.

Requires an explicitly configured LOCAL test_ database; never connects to
Render/production. Each run creates and drops only its own randomized schema.
Without that environment variable this test is skipped, NOT certified.
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
from app.paper_risk_reservations import PaperRiskReservationStore

ACCOUNT = "paper-race-account-0001"


def test_postgres_reservation_race_kill_and_atomic_audit():
    raw = os.getenv("PAPER_RISK_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("PostgreSQL risk CAS NOT CERTIFIED: supply a LOCAL test_ database")
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql"
            or url.host not in ("localhost", "127.0.0.1", "db")
            or not (url.database or "").startswith("test_") or url.query):
        pytest.fail("Refusing non-local, non-test_, or parameterized PostgreSQL URL")

    schema = "test_paper_risk_" + uuid.uuid4().hex
    engine = create_engine(url, pool_size=3, max_overflow=0,
                           connect_args={"connect_timeout": 3})
    created = False
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True

        @event.listens_for(engine, "begin")
        def isolate(connection):
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("SET LOCAL statement_timeout TO '10s'")

        Base.metadata.create_all(engine)
        factory = sessionmaker(engine)
        store = PaperRiskReservationStore(factory)
        assert store.initialize(ACCOUNT)
        assert store.set_policy(ACCOUNT, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)

        # Both independent connections read revision 1 before either updates.
        barrier = threading.Barrier(2, timeout=6)

        @event.listens_for(engine, "after_cursor_execute")
        def synchronize_reads(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT RECORDS.VALUE"):
                barrier.wait()

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(store.reserve, ACCOUNT, 1,
                                client_order_id="race-order-0001", risk_cash="60")
                b = pool.submit(store.reserve, ACCOUNT, 1,
                                client_order_id="race-order-0002", risk_cash="60")
                results = [a.result(timeout=12), b.result(timeout=12)]
        finally:
            event.remove(engine, "after_cursor_execute", synchronize_reads)

        assert sorted(results) == [False, True]
        snapshot = PaperRiskReservationStore(factory).load(ACCOUNT)
        assert snapshot["revision"] == 2
        assert snapshot["reserved_cash"] == "60"
        assert snapshot["reservation_count"] == 1
        assert snapshot["may_execute_real_order"] is False
        assert not store.reserve(ACCOUNT, 2, client_order_id="race-order-0003",
                                 risk_cash="60")
        with factory() as db:
            assert len(db.scalars(select(Audit).where(
                Audit.action == "paper.risk.cas")).all()) == 2

        # Audit-write interruption must roll back an otherwise VALID policy
        # mutation. Run before the emergency latch: latched policies reject
        # before audit insertion, which would never exercise rollback.
        before = store.load(ACCOUNT)

        @event.listens_for(engine, "before_cursor_execute")
        def interrupt_audit(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
                raise RuntimeError("synthetic risk audit failure")

        try:
            with pytest.raises(RuntimeError, match="synthetic risk audit failure"):
                store.set_policy(ACCOUNT, before["revision"], limit_cash="200",
                                 kill_switch=True, owner_reviewed=True)
        finally:
            event.remove(engine, "before_cursor_execute", interrupt_audit)
        assert PaperRiskReservationStore(factory).load(ACCOUNT) == before
        with factory() as db:
            assert len(db.scalars(select(Audit).where(
                Audit.action == "paper.risk.cas")).all()) == 2

        # A committed emergency stop survives process/store restart and rejects
        # all subsequent paper reservations, including stale revisions.
        assert store.engage_kill_switch(ACCOUNT)
        stopped = PaperRiskReservationStore(factory).load(ACCOUNT)
        assert stopped["kill_switch"] is True and stopped["emergency_latched"] is True
        assert not store.set_policy(ACCOUNT, stopped["revision"], limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
        assert PaperRiskReservationStore(factory).load(ACCOUNT) == stopped
        assert not store.reserve(ACCOUNT, 3, client_order_id="race-order-0004",
                                 risk_cash="1")

    finally:
        # Never touch an existing owner schema or any other database objects.
        try:
            if created:
                with engine.begin() as conn:
                    conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            engine.dispose()
