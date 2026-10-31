"""Bounded PAPER audit histories must retain a durable emergency-stop slot.

Synthetic SQLite only: no authenticated broker state or execution permission.
"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


def test_bounded_history_keeps_final_revision_for_emergency_latch(tmp_path, monkeypatch):
    # Five receipts: init + three ordinary CAS + one emergency CAS.
    # The production limit remains 4096; this exercises the boundary cheaply.
    monkeypatch.setattr(risk, "_MAX_AUDIT_HISTORY_ROWS", 5)
    engine = create_engine("sqlite:///" + str(tmp_path / "audit-cap.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    try:
        assert store.initialize(account)  # revision 0
        assert store.set_policy(account, 0, limit_cash="100", kill_switch=False,
                                owner_reviewed=True)  # revision 1
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="10")  # revision 2
        assert store.set_policy(account, 2, limit_cash="110", kill_switch=False,
                                owner_reviewed=True)  # revision 3, real cap change

        snapshot = risk.PaperRiskReservationStore(factory).load(account)
        assert snapshot["revision"] == 3
        assert snapshot["audit_head_verified"] is True
        assert snapshot["kill_switch"] is False
        assert snapshot["remaining_risk_capacity_cash"] == "100"
        assert snapshot["reservable_risk_capacity_cash"] == "0"
        assert snapshot["may_execute_paper_order"] is False
        assert snapshot["may_execute_real_order"] is False
        with factory() as db:
            before = db.scalars(select(Audit.detail).order_by(Audit.id)).all()
        assert len(before) == 4

        # No ordinary mutation may consume the last verifiable receipt.
        assert not store.reserve(account, 3, client_order_id="order-00002",
                                 risk_cash="1")
        assert not store.set_policy(account, 3, limit_cash="100",
                                    kill_switch=True, owner_reviewed=True)
        with factory() as db:
            assert db.scalars(select(Audit.detail).order_by(Audit.id)).all() == before

        # A restart still has the one remaining durable emergency-stop slot.
        restarted = risk.PaperRiskReservationStore(factory)
        assert restarted.engage_kill_switch(account)
        stopped = restarted.load(account)
        assert stopped["revision"] == 4
        assert stopped["audit_head_verified"] is True
        assert stopped["emergency_latched"] is True
        assert stopped["kill_switch"] is True
        assert stopped["reservable_risk_capacity_cash"] == "0"
        assert restarted.verify_audit_head(account)
        assert restarted.engage_kill_switch(account)  # idempotent, no extra receipt
        with factory() as db:
            assert len(db.scalars(select(Audit.id)).all()) == 5
        assert not restarted.reserve(account, 4, client_order_id="order-00003",
                                     risk_cash="1")
    finally:
        engine.dispose()


def test_history_cap_does_not_block_other_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(risk, "_MAX_AUDIT_HISTORY_ROWS", 5)
    engine = create_engine("sqlite:///" + str(tmp_path / "audit-isolation.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    try:
        for account in ("paper-acct-0001", "paper-acct-0002"):
            assert store.initialize(account)
            assert store.set_policy(account, 0, limit_cash="20",
                                    kill_switch=False, owner_reviewed=True)
        assert store.reserve("paper-acct-0001", 1,
                             client_order_id="order-00001", risk_cash="1")
        assert store.set_policy("paper-acct-0001", 2, limit_cash="21",
                                kill_switch=False, owner_reviewed=True)
        assert not store.reserve("paper-acct-0001", 3,
                                 client_order_id="order-00002", risk_cash="1")
        assert store.reserve("paper-acct-0002", 1,
                             client_order_id="order-00003", risk_cash="1")
        assert store.load("paper-acct-0002")["audit_head_verified"] is True
        assert store.load("paper-acct-0002")["reservable_risk_capacity_cash"] == "19"
    finally:
        engine.dispose()
