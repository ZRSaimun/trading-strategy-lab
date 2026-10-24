"""Opt-in, isolated PostgreSQL integration test for paper-journal CAS.

Only a LOCAL, explicitly named test_ database is accepted. No production URL is
read implicitly. The temporary schema is unique to this test and dropped at end.
Run with PAPER_JOURNAL_TEST_DATABASE_URL=postgresql+psycopg://.../test_paper.
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
from app.db import Base, Record, Audit
from app.paper_journal_store import PaperJournalStore

IDENTITY = {"instrument": "XAUUSD-DEMO", "provider": "TEST", "venue": "LOCAL",
            "priceSide": "bid-ask", "pointValue": 1}


def checkpoint(tag):
    return json.dumps({"version": 1, "identity": IDENTITY, "actions": [tag],
                       "orders": [], "events": []}, separators=(",", ":"))


def test_postgres_two_connections_and_atomic_audit_rollback():
    raw = os.getenv("PAPER_JOURNAL_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Set PAPER_JOURNAL_TEST_DATABASE_URL to an isolated LOCAL test_ PostgreSQL database")
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql" or url.host not in ("localhost", "127.0.0.1", "db")
            or not (url.database or "").startswith("test_") or url.query):
        pytest.fail("Refusing non-local or non-test_ PostgreSQL database")
    schema = "test_paper_" + uuid.uuid4().hex
    engine = create_engine(url, pool_size=3, max_overflow=0, connect_args={"connect_timeout": 3})
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        @event.listens_for(engine, "begin")
        def isolate(connection):
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("SET LOCAL statement_timeout TO '10s'")
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine)
        store = PaperJournalStore(factory)
        assert store.compare_and_swap("race", IDENTITY, None, 0, checkpoint("seed"))

        barrier = threading.Barrier(2, timeout=6)
        @event.listens_for(engine, "after_cursor_execute")
        def synchronize_reads(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT RECORDS.VALUE"):
                barrier.wait()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(store.compare_and_swap, "race", IDENTITY, 0, 1, checkpoint("writer-a"))
                b = pool.submit(store.compare_and_swap, "race", IDENTITY, 0, 1, checkpoint("writer-b"))
                results = [a.result(timeout=12), b.result(timeout=12)]
        finally:
            event.remove(engine, "after_cursor_execute", synchronize_reads)
        assert sorted(results) == [False, True]
        saved = PaperJournalStore(factory).load("race")
        assert saved["revision"] == 1
        assert saved["json"] in (checkpoint("writer-a"), checkpoint("writer-b"))
        with factory() as db:
            assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 2
            assert len(db.scalars(select(Record).where(Record.key.like("paper-journal:%"))).all()) == 1

        @event.listens_for(engine, "before_cursor_execute")
        def interrupt_audit(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
                raise RuntimeError("synthetic interruption before audit")
        try:
            with pytest.raises(RuntimeError, match="synthetic interruption"):
                store.compare_and_swap("race", IDENTITY, 1, 2, checkpoint("should-rollback"))
        finally:
            event.remove(engine, "before_cursor_execute", interrupt_audit)
        assert PaperJournalStore(factory).load("race") == saved
        with factory() as db:
            assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 2
        assert store.compare_and_swap("race", IDENTITY, 1, 2, checkpoint("retry"))
        assert PaperJournalStore(factory).load("race")["revision"] == 2
    finally:
        # Remove only our randomized test schema, never public or owner data.
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            engine.dispose()
