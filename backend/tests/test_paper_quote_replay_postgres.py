"""Disposable PostgreSQL concurrency/rollback acceptance for quote replay markers.

Never use an existing production database. A loopback-only *_test database is
required, and each run creates and drops only its random isolated schema.
No broker connectivity or order execution is exercised.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, current_thread
from uuid import uuid4
import os

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Record
from app.paper_quote_replay_store import PaperQuoteReplayStore

SOURCE = {
    "account_alias": "synthetic-paper",
    "provider": "SyntheticProvider",
    "venue": "TEST-OTC",
    "instrument": "XAUUSD-TEST",
}
NOW = 1_800_000_000_000


def quote(sequence):
    return {
        "quote_id": f"quote-id-{sequence:05d}",
        "sequence": sequence,
        "observed_at_ms": NOW + (sequence - 1) * 100,
        "received_at_ms": NOW + (sequence - 1) * 100 + 20,
        "bid": "4000.00",
        "ask": "4000.50",
    }


@pytest.fixture
def pg_store():
    raw_url = os.getenv("TSL_PG_QUOTE_TEST_URL")
    if not raw_url:
        pytest.skip("Disposable PostgreSQL quote test URL not configured")
    url = make_url(raw_url)
    if (url.get_backend_name() != "postgresql"
            or url.host not in ("127.0.0.1", "localhost", "::1")
            or not url.database or not url.database.endswith("_test")
            or url.query):
        pytest.fail("Refusing non-loopback, non-*_test or parameterized PostgreSQL URL")

    schema = "quote_accept_" + uuid4().hex
    admin = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

    engine = create_engine(
        url, pool_pre_ping=True, pool_size=4, max_overflow=0, pool_timeout=10,
        connect_args={"connect_timeout": 10, "options": f"-csearch_path={schema}"},
    )
    try:
        Record.__table__.create(engine)
        Audit.__table__.create(engine)
        factory = sessionmaker(engine)
        yield PaperQuoteReplayStore(factory), engine, factory
    finally:
        engine.dispose()
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def _race(engine, writer):
    barrier = Barrier(2, timeout=15)

    def after_read(_connection, _cursor, statement, _params, _context, _many):
        normalized = " ".join(statement.lower().split())
        if (current_thread().name.startswith("quote-writer")
                and normalized.startswith("select records.value")
                and "where records.key" in normalized):
            barrier.wait()

    event.listen(engine, "after_cursor_execute", after_read)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="quote-writer") as pool:
            futures = [pool.submit(writer) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]
    finally:
        event.remove(engine, "after_cursor_execute", after_read)


def _assert_one_winner(results, store, factory, revision, sequence, audits):
    assert sorted(result["status"] for result in results) == [
        "ACCEPTED_UNVERIFIED", "HOLD_RECONCILIATION"
    ]
    assert all(not result["quote_authenticated"] for result in results)
    assert all(not result["paper_order_permitted"] for result in results)
    assert all(not result["live_order_permitted"] for result in results)
    marker = store.load_marker(SOURCE)
    assert marker["revision"] == revision
    assert marker["sequence"] == sequence
    with factory() as session:
        actions = session.scalars(
            select(Audit.action).where(Audit.action == "paper.quote.observe")
        ).all()
    assert len(actions) == audits


def test_postgres_concurrent_initial_quote_only_one_writer(pg_store):
    store, engine, factory = pg_store
    results = _race(engine, lambda: store.observe(SOURCE, quote(1), now_ms=NOW + 30))
    _assert_one_winner(results, store, factory, revision=0, sequence=1, audits=1)


def test_postgres_concurrent_cas_only_one_revision(pg_store):
    store, engine, factory = pg_store
    assert store.observe(SOURCE, quote(1), now_ms=NOW + 30)["revision"] == 0
    results = _race(engine, lambda: store.observe(SOURCE, quote(2), now_ms=NOW + 130))
    _assert_one_winner(results, store, factory, revision=1, sequence=2, audits=2)


def test_postgres_audit_failure_rolls_back_insert_and_update(pg_store):
    store, engine, factory = pg_store

    def fail_audit(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic audit failure")

    event.listen(engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            store.observe(SOURCE, quote(1), now_ms=NOW + 30)
    finally:
        event.remove(engine, "before_cursor_execute", fail_audit)

    assert store.load_marker(SOURCE) is None
    assert store.observe(SOURCE, quote(1), now_ms=NOW + 30)["revision"] == 0

    event.listen(engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            store.observe(SOURCE, quote(2), now_ms=NOW + 130)
    finally:
        event.remove(engine, "before_cursor_execute", fail_audit)

    assert store.load_marker(SOURCE)["revision"] == 0
    assert store.observe(SOURCE, quote(2), now_ms=NOW + 130)["revision"] == 1
    with factory() as session:
        actions = session.scalars(
            select(Audit.action).where(Audit.action == "paper.quote.observe")
        ).all()
    assert len(actions) == 2
