"""Retained PAPER audit chronology is checked without claiming a trusted clock.

Synthetic SQLite only. An emergency latch may be backdated by clock rollback,
but an ordinary policy/reservation receipt may not precede its predecessor.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


@pytest.mark.parametrize("tampered_revision", [1, 2])
def test_backdated_old_ordinary_receipt_quarantines_account(
        tmp_path, monkeypatch, tampered_revision):
    engine = create_engine("sqlite:///" + str(tmp_path / "historical-clock.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        # Five same-account receipts leave both recent checkpoints unchanged
        # when revision 1 or 2 is backdated.
        for revision in range(5):
            with monkeypatch.context() as patch:
                patch.setattr(risk.time, "time", lambda r=revision: 2_000_000_000 + r)
                if revision == 0:
                    assert store.initialize(account)
                elif revision == 1:
                    assert store.set_policy(account, 0, limit_cash="100",
                                            kill_switch=False, owner_reviewed=True)
                else:
                    assert store.reserve(
                        account, revision - 1,
                        client_order_id=f"order-0000{revision - 1}", risk_cash="10")
        assert store.initialize(other)
        good = store.load(account)
        assert good["audit_head_verified"] is True
        key = store._key(account)
        with factory.begin() as db:
            rows = db.scalars(select(Audit).where(
                risk._account_audit_match(key)
            ).order_by(Audit.id.asc())).all()
            assert len(rows) == 5
            original_time = rows[tampered_revision].time
            rows[tampered_revision].time = rows[tampered_revision - 1].time - 1
        with factory() as db:
            before_count = db.scalar(select(func.count(Audit.id)))
            before_state = db.scalar(select(Record.value).where(Record.key == key))

        snapshot = store.load(account)
        assert snapshot["audit_head_verified"] is False
        assert snapshot["reservable_risk_capacity_cash"] == "0"
        assert store.verify_audit_head(account) is False
        assert store.verify_audit_head(other) is True
        with pytest.raises(ValueError, match="audit head"):
            store.reserve(account, 4, client_order_id="order-00004", risk_cash="1")
        with pytest.raises(ValueError, match="audit head"):
            store.set_policy(account, 4, limit_cash="110",
                             kill_switch=False, owner_reviewed=True)
        with pytest.raises(ValueError, match="audit head"):
            store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == before_count
            assert db.scalar(select(Record.value).where(Record.key == key)) == before_state

        # A reviewed restoration of the exact historical value is sufficient
        # to restore this internal check; it is not independent authentication.
        with factory.begin() as db:
            row = db.scalars(select(Audit).where(
                risk._account_audit_match(key)
            ).order_by(Audit.id.asc())).all()[tampered_revision]
            row.time = original_time
        assert store.verify_audit_head(account)
    finally:
        engine.dispose()


def test_emergency_latch_remains_verifiable_during_clock_rollback(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "emergency-clock.db"))
    Base.metadata.create_all(engine)
    store = risk.PaperRiskReservationStore(sessionmaker(engine))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: 2_000_000_100)
            assert store.initialize("paper-acct-0001")
            assert store.set_policy("paper-acct-0001", 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
            patch.setattr(risk.time, "time", lambda: 2_000_000_050)
            assert store.engage_kill_switch("paper-acct-0001")
        restarted = risk.PaperRiskReservationStore(sessionmaker(engine))
        assert restarted.verify_audit_head("paper-acct-0001")
        state = restarted.load("paper-acct-0001")
        assert state["emergency_latched"] is True
        assert state["reservable_risk_capacity_cash"] == "0"
        assert state["may_execute_paper_order"] is False
        assert state["may_execute_real_order"] is False
    finally:
        engine.dispose()
