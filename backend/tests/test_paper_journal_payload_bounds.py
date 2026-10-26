"""Fail-closed paper journal checkpoint and stored-envelope bounds.

Synthetic SQLite only: not evidence of authenticated quotes, broker execution,
PostgreSQL process-crash recovery, or real-money trading safety.
"""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base, Record
from app.paper_journal_store import (
    MAX_ACTIONS, MAX_CHECKPOINT_BYTES, MAX_ENVELOPE_BYTES, PaperJournalStore,
)

IDENTITY = {
    "instrument": "XAUUSD-DEMO",
    "provider": "SYNTHETIC",
    "venue": "TEST",
    "priceSide": "bid-ask",
    "pointValue": 1,
}


def checkpoint(*, version=1, actions=None, orders=None, events=None):
    return json.dumps({
        "version": version, "identity": IDENTITY,
        "actions": [] if actions is None else actions,
        "orders": [] if orders is None else orders,
        "events": [] if events is None else events,
    }, separators=(",", ":"))


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "bounded.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield PaperJournalStore(factory), factory
    engine.dispose()


@pytest.mark.parametrize("version", [True, 1.0, "1", False, None, 2])
def test_non_exact_checkpoint_version_rejected_before_write(store, version):
    journal, factory = store
    with pytest.raises(ValueError, match="schema"):
        journal.compare_and_swap("version", IDENTITY, None, 0, checkpoint(version=version))
    assert journal.load("version") is None
    with factory() as db:
        assert not db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()


@pytest.mark.parametrize("field", ["actions", "orders", "events"])
def test_each_checkpoint_collection_has_same_upper_bound(store, field):
    journal, factory = store
    payload = {field: [0] * (MAX_ACTIONS + 1)}
    with pytest.raises(ValueError, match="collections"):
        journal.compare_and_swap("over-limit", IDENTITY, None, 0, checkpoint(**payload))
    assert journal.load("over-limit") is None
    with factory() as db:
        assert not db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()


def test_exact_collection_boundary_preserves_valid_checkpoint(store):
    journal, _ = store
    payload = checkpoint(events=[0] * MAX_ACTIONS)
    assert len(payload.encode("utf-8")) < MAX_CHECKPOINT_BYTES
    assert journal.compare_and_swap("boundary", IDENTITY, None, 0, payload)
    assert journal.load("boundary")["json"] == payload


def test_oversized_persisted_envelope_blocks_load_and_cas_without_audit(store):
    journal, factory = store
    assert journal.compare_and_swap("damaged", IDENTITY, None, 0, checkpoint())
    key = journal._key("damaged")
    with factory.begin() as db:
        db.get(Record, key).value = " " * (MAX_ENVELOPE_BYTES + 1)
    with pytest.raises(ValueError, match="corrupt"):
        journal.load("damaged")
    with pytest.raises(ValueError, match="corrupt"):
        journal.compare_and_swap("damaged", IDENTITY, 0, 1, checkpoint(actions=[1]))
    with factory() as db:
        rows = db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()
        assert len(rows) == 1
        assert db.get(Record, key).value == " " * (MAX_ENVELOPE_BYTES + 1)


def test_corrupt_stored_boolean_checkpoint_version_blocks_restart(store):
    journal, factory = store
    assert journal.compare_and_swap("restart", IDENTITY, None, 0, checkpoint())
    key = journal._key("restart")
    with factory.begin() as db:
        record = db.get(Record, key)
        envelope = json.loads(record.value)
        envelope["json"] = checkpoint(version=True)
        import hashlib
        envelope["sha256"] = hashlib.sha256(envelope["json"].encode("utf-8")).hexdigest()
        record.value = json.dumps(envelope)
    with pytest.raises(ValueError, match="corrupt"):
        PaperJournalStore(factory).load("restart")
