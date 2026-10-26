"""SQLite regression tests for server-anchored standalone paper journal CAS.

No broker authentication, execution permission, or PostgreSQL race proof.
"""
import copy
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base
from app.paper_journal_store import PaperJournalStore


IDENTITY = {
    "instrument": "XAUUSD-DEMO", "provider": "SYNTHETIC",
    "venue": "TEST", "priceSide": "bid-ask", "pointValue": 1,
}


def state():
    return {
        "version": 1, "identity": IDENTITY,
        "actions": [{"kind": "SUBMIT", "request": {"clientOrderId": "order-a"}}],
        "orders": [{"clientOrderId": "order-a", "status": "PENDING"}],
        "events": [{"orderId": "order-a", "status": "PENDING", "at": 1}],
    }


def advance(before):
    after = copy.deepcopy(before)
    after["actions"].append({"kind": "QUOTE", "bid": 4000, "ask": 4001})
    after["orders"][0]["status"] = "OPEN"  # Derived state may legitimately advance.
    after["events"].append({"orderId": "order-a", "status": "OPEN", "at": 2})
    return after


def encoded(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@pytest.fixture
def journal(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "continuity.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield PaperJournalStore(factory), factory
    engine.dispose()


def test_legitimate_append_and_derived_order_status_change_survive_restart(journal):
    store, factory = journal
    before = state()
    after = advance(before)
    assert store.compare_and_swap("session-a", IDENTITY, None, 0, encoded(before))
    assert store.compare_and_swap("session-a", IDENTITY, 0, 1, encoded(after))
    restarted = PaperJournalStore(factory)
    assert restarted.load("session-a")["revision"] == 1
    assert restarted.load("session-a")["json"] == encoded(after)
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 2


@pytest.mark.parametrize("mutation", [
    "erase_actions", "rewrite_action", "no_new_action",
    "erase_events", "rewrite_event", "erase_orders",
    "duplicate_order_id", "malformed_order_id",
])
def test_history_tampering_never_updates_checkpoint_or_audit(journal, mutation):
    store, factory = journal
    before = state()
    proposed = advance(before)
    assert store.compare_and_swap("session-b", IDENTITY, None, 0, encoded(before))
    if mutation == "erase_actions":
        proposed["actions"] = []
    elif mutation == "rewrite_action":
        proposed["actions"][0]["request"]["clientOrderId"] = "order-forged"
    elif mutation == "no_new_action":
        proposed["actions"] = copy.deepcopy(before["actions"])
    elif mutation == "erase_events":
        proposed["events"] = []
    elif mutation == "rewrite_event":
        proposed["events"][0]["at"] = 99
    elif mutation == "erase_orders":
        proposed["orders"] = []
    elif mutation == "duplicate_order_id":
        proposed["orders"].append(copy.deepcopy(proposed["orders"][0]))
    elif mutation == "malformed_order_id":
        proposed["orders"][0]["clientOrderId"] = "../../secret"
    with pytest.raises(ValueError, match="continuity violation"):
        store.compare_and_swap("session-b", IDENTITY, 0, 1, encoded(proposed))
    assert PaperJournalStore(factory).load("session-b")["json"] == encoded(before)
    assert store.load("session-b")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 1


def test_order_identifier_reordering_fails_even_with_valid_actions(journal):
    store, factory = journal
    before = state()
    before["orders"].append({"clientOrderId": "order-b", "status": "PENDING"})
    after = advance(before)
    after["orders"].reverse()
    assert store.compare_and_swap("session-c", IDENTITY, None, 0, encoded(before))
    with pytest.raises(ValueError, match="continuity violation"):
        store.compare_and_swap("session-c", IDENTITY, 0, 1, encoded(after))
    assert store.load("session-c")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 1


def test_stale_cas_does_not_overwrite_accepted_history(journal):
    store, factory = journal
    before = state()
    after = advance(before)
    assert store.compare_and_swap("session-d", IDENTITY, None, 0, encoded(before))
    assert store.compare_and_swap("session-d", IDENTITY, 0, 1, encoded(after))
    assert not store.compare_and_swap("session-d", IDENTITY, 0, 1, encoded(advance(before)))
    assert store.load("session-d")["json"] == encoded(after)
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 2
