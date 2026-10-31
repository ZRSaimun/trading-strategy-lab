"""Repeated identical PAPER policy reviews must not exhaust bounded audit slots.

Synthetic SQLite only. This prototype never grants execution permission.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


@pytest.mark.parametrize("stage", ["initialized", "enabled", "reserved"])
def test_identical_policy_rejected_without_revision_or_audit(tmp_path, stage):
    engine = create_engine("sqlite:///" + str(tmp_path / f"noop-{stage}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.initialize(other)
        cap, stopped = "0", True
        if stage != "initialized":
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
            cap, stopped = "100", False
        if stage == "reserved":
            assert store.reserve(account, 1, client_order_id="order-00001",
                                 risk_cash="10")
        snapshot = store.load(account)
        with factory() as db:
            before = db.scalars(select(Audit.detail).order_by(Audit.id)).all()

        assert store.set_policy(account, snapshot["revision"], limit_cash=cap,
                                kill_switch=stopped, owner_reviewed=True) is False
        assert store.set_policy(account, snapshot["revision"], limit_cash=cap,
                                kill_switch=stopped, owner_reviewed=True) is False
        assert risk.PaperRiskReservationStore(factory).load(account) == snapshot
        assert store.verify_audit_head(account)
        assert store.verify_audit_head(other)
        with factory() as db:
            assert db.scalars(select(Audit.detail).order_by(Audit.id)).all() == before

        # A real reviewed change remains possible at the original revision.
        new_cap = "100" if stage == "initialized" else "101"
        assert store.set_policy(account, snapshot["revision"], limit_cash=new_cap,
                                kill_switch=stopped, owner_reviewed=True)
        changed = store.load(account)
        assert changed["revision"] == snapshot["revision"] + 1
        assert changed["limit_cash"] == new_cap
        assert changed["audit_head_verified"] is True
        assert changed["may_execute_paper_order"] is False
    finally:
        engine.dispose()


def test_identical_policy_cannot_consume_emergency_stop_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(risk, "_MAX_AUDIT_HISTORY_ROWS", 5)
    engine = create_engine("sqlite:///" + str(tmp_path / "noop-stop-slot.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    try:
        assert store.initialize(account)  # revision 0
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)  # revision 1
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="10")  # revision 2; only stop slot remains
        with factory() as db:
            before = db.scalars(select(Audit.detail).order_by(Audit.id)).all()
        for _ in range(3):
            assert not store.set_policy(account, 2, limit_cash="100",
                                        kill_switch=False, owner_reviewed=True)
        with factory() as db:
            assert db.scalars(select(Audit.detail).order_by(Audit.id)).all() == before
        # The no-op requests did not consume the last ordinary CAS slot.
        assert store.reserve(account, 2, client_order_id="order-00002",
                             risk_cash="5")  # revision 3
        assert risk.PaperRiskReservationStore(factory).engage_kill_switch(account)
        final = store.load(account)
        assert final["revision"] == 4
        assert final["emergency_latched"] is True
        assert final["audit_head_verified"] is True
        assert final["reservable_risk_capacity_cash"] == "0"
    finally:
        engine.dispose()


def test_policy_cash_text_change_remains_audited(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "policy-text.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    try:
        assert store.initialize("paper-acct-0001")
        assert store.set_policy("paper-acct-0001", 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        # Exact representation is retained in signed-off policy receipts.
        assert store.set_policy("paper-acct-0001", 1, limit_cash="100.00",
                                kill_switch=False, owner_reviewed=True)
        snapshot = store.load("paper-acct-0001")
        assert snapshot["revision"] == 2
        assert snapshot["limit_cash"] == "100.00"
        assert snapshot["audit_head_verified"] is True
    finally:
        engine.dispose()
