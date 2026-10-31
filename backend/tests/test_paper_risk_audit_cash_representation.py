"""Reject numerically equal but byte-rewritten historical PAPER cash receipts.

Synthetic SQLite tampering only. No broker or real account evidence is used.
"""
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


@pytest.mark.parametrize(
    "old_revision,first_cash,replacement",
    [
        (1, "1", "0.00"),
        (1, "1", "0E+999999999"),
        (2, "1", "1.0"),
        (2, "1", "1.00"),
    ],
)
def test_old_cash_representation_mutation_fails_closed(
        tmp_path, old_revision, first_cash, replacement):
    engine = create_engine("sqlite:///" + str(tmp_path / "cash-history.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.initialize(other)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash=first_cash)
        assert store.reserve(account, 2, client_order_id="order-00002",
                             risk_cash="2")
        assert store.verify_audit_head(account)
        with factory.begin() as db:
            receipts = db.scalars(select(Audit).where(
                risk._account_audit_match(store._key(account))
            ).order_by(Audit.id.asc())).all()
            assert len(receipts) == 4
            older = receipts[old_revision]
            detail = json.loads(older.detail)
            assert detail["reserved_cash"] == ("0" if old_revision == 1 else "1")
            detail["reserved_cash"] = replacement
            older.detail = risk._canonical(detail)
        with factory() as db:
            count_before = db.scalar(select(func.count(Audit.id)))
        snapshot = store.load(account)
        assert snapshot["audit_head_verified"] is False
        assert snapshot["reservable_risk_capacity_cash"] == "0"
        assert not store.verify_audit_head(account)
        with pytest.raises(ValueError, match="audit head"):
            store.reserve(account, 3, client_order_id="order-00003",
                          risk_cash="1")
        with pytest.raises(ValueError, match="audit head"):
            store.set_policy(account, 3, limit_cash="100",
                             kill_switch=True, owner_reviewed=True)
        with pytest.raises(ValueError, match="audit head"):
            store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == count_before
        assert store.verify_audit_head(other)
    finally:
        engine.dispose()


def test_genuine_scaled_decimal_cash_history_survives_restart(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "scaled-cash.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    try:
        store = risk.PaperRiskReservationStore(factory)
        account = "paper-acct-0001"
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100.00",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="1.00")
        assert store.reserve(account, 2, client_order_id="order-00002",
                             risk_cash="0.00000001")
        restarted = risk.PaperRiskReservationStore(factory)
        assert restarted.verify_audit_head(account)
        assert restarted.load(account)["reserved_cash"] == "1.00000001"
        assert restarted.engage_kill_switch(account)
        assert restarted.load(account)["emergency_latched"] is True
    finally:
        engine.dispose()
