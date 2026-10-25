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


# Atomic quote-marker + journal acceptance (same isolated PostgreSQL schema).
from app.paper_quote_journal_atomic import AtomicPaperQuoteJournalStore
from app.paper_journal_store import PaperJournalStore
import json


JOURNAL_IDENTITY = {
    "instrument": "XAUUSD-TEST", "provider": "SyntheticProvider",
    "venue": "TEST-OTC", "priceSide": "bid-ask", "pointValue": 1,
}


def _checkpoint_json(sequence):
    return json.dumps({
        "version": 1, "identity": JOURNAL_IDENTITY,
        "actions": [f"synthetic-{sequence}"], "orders": [], "events": [],
    }, separators=(",", ":"))


def _atomic_checkpoint(store, sequence, expected_revision=None):
    return store.checkpoint(
        SOURCE, quote(sequence), "pg-atomic-journal", JOURNAL_IDENTITY,
        expected_revision, 0 if expected_revision is None else expected_revision + 1,
        _checkpoint_json(sequence),
        now_ms=NOW + (sequence - 1) * 100 + 30,
    )


def test_postgres_atomic_quote_journal_first_writer_race(pg_store):
    quote_store, engine, factory = pg_store
    atomic = AtomicPaperQuoteJournalStore(factory)
    results = _race(engine, lambda: _atomic_checkpoint(atomic, 1))
    assert sorted(x["status"] for x in results) == [
        "CHECKPOINT_RECORDED_UNVERIFIED", "HOLD_RECONCILIATION",
    ]
    assert all(not x["paper_order_permitted"] and not x["live_order_permitted"] for x in results)
    assert quote_store.load_marker(SOURCE)["revision"] == 0
    assert PaperJournalStore(factory).load("pg-atomic-journal")["revision"] == 0
    with factory() as session:
        assert len(session.scalars(select(Audit)).all()) == 1
        assert len(session.scalars(select(Record)).all()) == 4


def test_postgres_atomic_quote_journal_revision_race(pg_store):
    quote_store, engine, factory = pg_store
    atomic = AtomicPaperQuoteJournalStore(factory)
    assert _atomic_checkpoint(atomic, 1)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    results = _race(engine, lambda: _atomic_checkpoint(atomic, 2, 0))
    assert sorted(x["status"] for x in results) == [
        "CHECKPOINT_RECORDED_UNVERIFIED", "HOLD_RECONCILIATION",
    ]
    assert quote_store.load_marker(SOURCE)["revision"] == 1
    assert PaperJournalStore(factory).load("pg-atomic-journal")["revision"] == 1
    with factory() as session:
        assert len(session.scalars(select(Audit)).all()) == 2


def test_postgres_atomic_quote_journal_audit_failure_rolls_back_all(pg_store):
    quote_store, engine, factory = pg_store
    atomic = AtomicPaperQuoteJournalStore(factory)

    def fail_audit(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic atomic audit interruption")

    event.listen(engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="atomic audit interruption"):
            _atomic_checkpoint(atomic, 1)
    finally:
        event.remove(engine, "before_cursor_execute", fail_audit)
    assert quote_store.load_marker(SOURCE) is None
    assert PaperJournalStore(factory).load("pg-atomic-journal") is None
    with factory() as session:
        assert session.scalars(select(Record)).all() == []
        assert session.scalars(select(Audit)).all() == []


def test_postgres_bound_atomic_journal_rejects_standalone_cas(pg_store):
    quote_store, _engine, factory = pg_store
    atomic = AtomicPaperQuoteJournalStore(factory)
    journal = PaperJournalStore(factory)
    assert _atomic_checkpoint(atomic, 1)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"

    # A separate writer must not advance the journal without advancing its
    # bound quote replay marker; rejected attempts must not add an audit.
    assert journal.compare_and_swap(
        "pg-atomic-journal", JOURNAL_IDENTITY, 0, 1, _checkpoint_json(2)
    ) is False
    assert journal.load("pg-atomic-journal")["revision"] == 0
    assert quote_store.load_marker(SOURCE)["revision"] == 0
    with factory() as session:
        assert len(session.scalars(select(Audit)).all()) == 1

    assert _atomic_checkpoint(atomic, 2, 0)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    assert journal.load("pg-atomic-journal")["revision"] == 1
    assert quote_store.load_marker(SOURCE)["revision"] == 1


def test_postgres_atomic_source_blocks_standalone_quote_writer(pg_store):
    quotes, _engine, factory = pg_store
    atomic = AtomicPaperQuoteJournalStore(factory)
    journal = PaperJournalStore(factory)
    assert _atomic_checkpoint(atomic, 1)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    result = quotes.observe(SOURCE, quote(2), now_ms=NOW + 130)
    assert result["reason"] == "ATOMIC_JOURNAL_OWNS_QUOTE_SOURCE"
    assert result["status"] == "HOLD_RECONCILIATION"
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert journal.load("pg-atomic-journal")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1
    assert _atomic_checkpoint(atomic, 2, 0)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"


def test_postgres_source_rejects_second_journal_binding(pg_store):
    quotes, _engine, factory = pg_store
    atomic = AtomicPaperQuoteJournalStore(factory)
    assert _atomic_checkpoint(atomic, 1)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    result = atomic.checkpoint(
        SOURCE, quote(2), "another-pg-journal", JOURNAL_IDENTITY,
        None, 0, _checkpoint_json(2), now_ms=NOW + 130,
    )
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "QUOTE_SOURCE_ALREADY_BOUND_TO_OTHER_JOURNAL"
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert PaperJournalStore(factory).load("another-pg-journal") is None
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1
