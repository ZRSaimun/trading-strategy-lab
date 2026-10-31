"""Synthetic orphan-audit regressions for disconnected PAPER-only reservations.

No broker, order sender, real market data, or production database is used.
"""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base, Record
from app.paper_risk_reservations import PaperRiskReservationStore


@pytest.fixture
def setup(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "orphan-risk.db"))
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


@pytest.mark.parametrize("last_transition", ["initialize", "policy", "reserve"])
def test_missing_state_with_retained_history_cannot_reinitialize(setup, last_transition):
    store = PaperRiskReservationStore(setup)
    account = "paper-acct-0001"
    assert store.initialize(account)
    if last_transition in ("policy", "reserve"):
        assert store.set_policy(account, 0, limit_cash="100", kill_switch=False,
                                owner_reviewed=True)
    if last_transition == "reserve":
        assert store.reserve(account, 1, client_order_id="order-00001", risk_cash="3")

    key = store._key(account)
    with setup.begin() as db:
        original_receipts = db.scalars(select(Audit.detail).order_by(Audit.id)).all()
        db.delete(db.get(Record, key))  # Synthetic lost state; retained audit survives.
    assert store.load(account) is None

    # A new revision-zero snapshot would falsely report a successful fresh
    # initialization while contradicting the retained historical receipts.
    assert not PaperRiskReservationStore(setup).initialize(account)
    assert store.load(account) is None
    assert not store.reserve(account, 0, client_order_id="order-00002", risk_cash="1")
    assert not store.engage_kill_switch(account)
    with setup() as db:
        assert db.get(Record, key) is None
        assert db.scalars(select(Audit.detail).order_by(Audit.id)).all() == original_receipts

    # The orphan belongs to this account only.
    assert store.initialize("paper-acct-0002")
    assert store.load("paper-acct-0002")["audit_head_verified"] is True


def test_unknown_action_with_same_account_hash_blocks_first_initialization(setup):
    store = PaperRiskReservationStore(setup)
    account = "paper-acct-0001"
    key = store._key(account)
    account_hash = key.split(":", 1)[1]
    detail = json.dumps({"account_hash": account_hash, "untrusted": True},
                        sort_keys=True, separators=(",", ":"))
    with setup.begin() as db:
        db.add(Audit(time=1, actor="synthetic-foreign", action="foreign.action",
                     detail=detail))
    assert not store.initialize(account)
    assert store.load(account) is None
    with setup() as db:
        assert db.get(Record, key) is None
        assert db.scalars(select(Audit.detail)).all() == [detail]
    assert store.initialize("paper-acct-0002")
    assert store.load("paper-acct-0002")["audit_head_verified"] is True
