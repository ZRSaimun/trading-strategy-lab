"""Idempotent PAPER emergency-stop acknowledgement must check its own snapshot.

Synthetic SQLite only; no broker, execution route or real account data.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.paper_risk_reservations import PaperRiskReservationStore
from app.db import Audit, Base


def test_latched_retry_verifies_same_loaded_checkpoint_in_one_session(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "latched-checkpoint.db"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    opened = [0]

    def counted_session():
        opened[0] += 1
        return sessions()

    store = PaperRiskReservationStore(counted_session)
    account = "paper-acct-0001"
    try:
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="10")
        assert store.engage_kill_switch(account)
        with sessions() as db:
            original_receipts = db.scalars(
                select(Audit.detail).order_by(Audit.id)
            ).all()

        opened[0] = 0
        assert store.engage_kill_switch(account) is True
        assert opened[0] == 1  # No second session for a different checkpoint.
        assert store.load(account)["emergency_latched"] is True
        with sessions() as db:
            assert db.scalars(select(Audit.detail).order_by(Audit.id)).all() == original_receipts
    finally:
        engine.dispose()


def test_corrupt_latched_audit_denies_idempotent_success_without_writes(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "latched-corrupt.db"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    opened = [0]

    def counted_session():
        opened[0] += 1
        return sessions()

    store = PaperRiskReservationStore(counted_session)
    account = "paper-acct-0001"
    try:
        assert store.initialize(account)
        assert store.engage_kill_switch(account)
        with sessions() as db:
            latest = db.scalar(select(Audit).order_by(Audit.id.desc()).limit(1))
            original = latest.detail
            latest.detail = original + " "  # Same JSON meaning; invalid canonical receipt.
            db.commit()
        with sessions() as db:
            corrupt_receipts = db.scalars(select(Audit.detail).order_by(Audit.id)).all()

        opened[0] = 0
        with pytest.raises(ValueError, match="audit head is missing or inconsistent"):
            store.engage_kill_switch(account)
        assert opened[0] == 1
        with sessions() as db:
            assert db.scalars(select(Audit.detail).order_by(Audit.id)).all() == corrupt_receipts

        # A manually restored valid receipt permits an idempotent retry;
        # the store never auto-repairs or invents an emergency-stop audit.
        with sessions() as db:
            latest = db.scalar(select(Audit).order_by(Audit.id.desc()).limit(1))
            latest.detail = original
            db.commit()
        opened[0] = 0
        assert store.engage_kill_switch(account)
        assert opened[0] == 1
    finally:
        engine.dispose()
