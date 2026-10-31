"""Disposable PostgreSQL acceptance for isolated paper risk persistence guards.

Never point this test at an existing database. It requires a loopback-only,
explicitly named test database, and creates/drops its own random schema.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, BrokenBarrierError, current_thread
from uuid import uuid4
from urllib.parse import urlsplit

import os
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Record
from app.paper_daily_loss_breaker import PaperDailyLossBreaker
from app.paper_order_intent_registry import PaperOrderIntentRegistry, _key


@pytest.fixture
def pg_factory():
    url = os.getenv("TSL_PG_RISK_TEST_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL test database not configured")
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    if (parsed.get_backend_name() != "postgresql"
            or parsed.host not in ("127.0.0.1", "localhost", "::1")
            or not parsed.database or not parsed.database.endswith("_test")):
        pytest.fail("Refusing PostgreSQL test outside a loopback *_test database")
    schema = "risk_accept_" + uuid4().hex
    admin = create_engine(url, pool_pre_ping=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = create_engine(
        url, pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=4, max_overflow=0,
    )
    try:
        Record.__table__.create(isolated)
        Audit.__table__.create(isolated)
        yield isolated, sessionmaker(isolated)
    finally:
        isolated.dispose()
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def test_competing_writers_only_one_revision_and_audit(pg_factory):
    engine, factory = pg_factory
    store = PaperDailyLossBreaker(factory)
    day = "2026-10-24"
    assert store.initialize("demo", day, "GBP", "100")
    # Both SELECTs must finish before either thread is permitted to UPDATE.
    barrier = Barrier(2, timeout=15)

    def synchronize_reads(_connection, _cursor, statement, _params, _context, _many):
        if (current_thread().name.startswith("risk-writer")
                and "records.value" in statement.lower()
                and statement.lstrip().upper().startswith("SELECT")):
            barrier.wait()

    event.listen(engine, "after_cursor_execute", synchronize_reads)
    try:
        def writer():
            return store.observe(
                "demo", day, sequence=1,
                observed_ms=1792800001000, now_ms=1792800001100,
                realized="-90", unrealized="-20", reserved="0",
            )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="risk-writer") as pool:
            futures = [pool.submit(writer) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
    finally:
        event.remove(engine, "after_cursor_execute", synchronize_reads)

    assert sum(isinstance(value, dict) for value in results) == 1
    assert sum(value is False for value in results) == 1
    snapshot = store.load("demo", day)
    assert snapshot["revision"] == 1
    assert snapshot["latched"] is True
    assert snapshot["peak_loss"] == "110"
    assert snapshot["may_execute_paper_order"] is False
    assert snapshot["may_execute_real_order"] is False
    with factory() as session:
        actions = session.scalars(select(Audit.action)).all()
    assert actions.count("paper.loss.initialize") == 1
    assert actions.count("paper.loss.observe") == 1


def test_postgres_audit_failure_rolls_back_risk_state(pg_factory):
    engine, factory = pg_factory
    store = PaperDailyLossBreaker(factory)
    day = "2026-10-24"
    assert store.initialize("demo", day, "GBP", "100")

    def reject_audit(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic audit failure")

    event.listen(engine, "before_cursor_execute", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            store.observe("demo", day, sequence=1,
                          observed_ms=1792800001000, now_ms=1792800001100,
                          realized="-110", unrealized="0", reserved="0")
    finally:
        event.remove(engine, "before_cursor_execute", reject_audit)

    assert store.load("demo", day)["revision"] == 0
    with factory() as session:
        assert session.scalars(select(Audit.action)).all() == ["paper.loss.initialize"]


# The same disposable, loopback-only PostgreSQL CI job also exercises the
# existing durable order-intent registry. This is DB safety, not broker proof.
_INTENT_ACCOUNT = "paper-account-001"
_INTENT_ORDER = "client-order-001"
_INTENT_HASH = "a" * 64
_INTENT_NOW = 1_798_000_000_000


def test_postgres_simultaneous_intent_registration_is_single_use(pg_factory):
    _, factory = pg_factory

    def writer():
        return PaperOrderIntentRegistry(factory).register(
            _INTENT_ACCOUNT, _INTENT_ORDER,
            review_sha256=_INTENT_HASH, now_ms=_INTENT_NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(writer) for _ in range(2)]]
    assert sorted(results) == [False, True]
    restarted = PaperOrderIntentRegistry(factory)
    assert not restarted.register(
        _INTENT_ACCOUNT, _INTENT_ORDER, review_sha256="b" * 64,
        now_ms=_INTENT_NOW + 120_000)
    snapshot = restarted.load(_INTENT_ACCOUNT, _INTENT_ORDER)
    assert snapshot["state"] == "PREVIEW_ONLY"
    assert snapshot["may_execute_paper_order"] is False
    assert snapshot["may_execute_real_order"] is False
    with factory() as session:
        audit = session.scalars(select(Audit)).all()
        records = session.scalars(select(Record)).all()
    assert [a.action for a in audit] == ["paper.intent.register"]
    assert len(records) == 1
    stored = records[0].key + records[0].value + audit[0].detail
    assert _INTENT_ACCOUNT not in stored and _INTENT_ORDER not in stored


def test_postgres_simultaneous_unknown_outcome_has_single_cas_and_audit(pg_factory):
    engine, factory = pg_factory
    store = PaperOrderIntentRegistry(factory)
    assert store.register(_INTENT_ACCOUNT, _INTENT_ORDER,
                          review_sha256=_INTENT_HASH, now_ms=_INTENT_NOW)
    barrier = Barrier(2, timeout=15)

    def synchronize_reads(_connection, _cursor, statement, _params, _context, _many):
        if (current_thread().name.startswith("intent-writer")
                and "records.value" in statement.lower()
                and statement.lstrip().upper().startswith("SELECT")):
            barrier.wait()

    event.listen(engine, "after_cursor_execute", synchronize_reads)
    try:
        def writer():
            return PaperOrderIntentRegistry(factory).mark_outcome_unknown(
                _INTENT_ACCOUNT, _INTENT_ORDER, review_sha256=_INTENT_HASH,
                expected_revision=0, now_ms=_INTENT_NOW + 100)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="intent-writer") as pool:
            results = [f.result(timeout=30) for f in [pool.submit(writer) for _ in range(2)]]
    finally:
        event.remove(engine, "after_cursor_execute", synchronize_reads)

    assert sorted(results) == [False, True]
    state = PaperOrderIntentRegistry(factory).load(_INTENT_ACCOUNT, _INTENT_ORDER)
    assert state["state"] == "OUTCOME_UNKNOWN"
    assert state["revision"] == 1
    assert state["requires_reconciliation"] is True
    assert state["may_execute_real_order"] is False
    assert not store.mark_outcome_unknown(
        _INTENT_ACCOUNT, _INTENT_ORDER, review_sha256=_INTENT_HASH,
        expected_revision=0, now_ms=_INTENT_NOW + 101)
    with factory() as session:
        actions = session.scalars(select(Audit.action).order_by(Audit.id)).all()
    assert actions == ["paper.intent.register", "paper.intent.quarantine"]


def test_postgres_intent_audit_failure_rolls_back_both_transitions(pg_factory):
    engine, factory = pg_factory
    store = PaperOrderIntentRegistry(factory)

    def reject_audit(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic intent audit failure")

    event.listen(engine, "before_cursor_execute", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic intent audit failure"):
            store.register(_INTENT_ACCOUNT, _INTENT_ORDER,
                           review_sha256=_INTENT_HASH, now_ms=_INTENT_NOW)
    finally:
        event.remove(engine, "before_cursor_execute", reject_audit)
    assert store.load(_INTENT_ACCOUNT, _INTENT_ORDER) is None

    assert store.register(_INTENT_ACCOUNT, _INTENT_ORDER,
                          review_sha256=_INTENT_HASH, now_ms=_INTENT_NOW)
    event.listen(engine, "before_cursor_execute", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic intent audit failure"):
            store.mark_outcome_unknown(
                _INTENT_ACCOUNT, _INTENT_ORDER, review_sha256=_INTENT_HASH,
                expected_revision=0, now_ms=_INTENT_NOW + 100)
    finally:
        event.remove(engine, "before_cursor_execute", reject_audit)

    assert store.load(_INTENT_ACCOUNT, _INTENT_ORDER)["state"] == "PREVIEW_ONLY"
    with factory() as session:
        actions = session.scalars(select(Audit.action)).all()
    assert actions == ["paper.intent.register"]
