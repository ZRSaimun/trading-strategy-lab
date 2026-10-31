"""Reject nonportable generated audit IDs without committing paired PAPER state.

Synthetic SQLite ROWID exhaustion only. No broker, market or live-order data.
"""
import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


@pytest.mark.parametrize("operation", ["initialize", "policy", "reserve", "emergency_kill"])
def test_generated_int4_audit_id_overflow_rolls_back_state_and_receipt(
        tmp_path, operation):
    engine = create_engine("sqlite:///" + str(tmp_path / f"audit-id-{operation}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        if operation in ("reserve", "emergency_kill"):
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
        key = store._key(account)
        with factory.begin() as db:
            latest = db.scalar(select(Audit).where(
                risk._account_audit_match(key)
            ).order_by(Audit.id.desc()).limit(1))
            original_id = latest.id
            # The existing receipt remains valid at the inclusive INT4
            # boundary; the *next* SQLite-generated ROWID will overflow.
            latest.id = risk._MAX_AUDIT_ID

        assert store.verify_audit_head(account)
        with factory() as db:
            original_state = db.scalar(select(Record.value).where(Record.key == key))
            original_count = db.scalar(select(func.count(Audit.id)))

        def attempt():
            if operation == "initialize":
                return store.initialize(other)
            if operation == "policy":
                return store.set_policy(account, 0, limit_cash="100",
                                        kill_switch=False, owner_reviewed=True)
            if operation == "reserve":
                return store.reserve(account, 1, client_order_id="order-00001",
                                     risk_cash="10")
            return store.engage_kill_switch(account)

        with pytest.raises(ValueError, match="audit ID"):
            attempt()
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == original_count
            assert db.scalar(select(func.max(Audit.id))) == risk._MAX_AUDIT_ID
            assert db.scalar(select(Record.value).where(Record.key == key)) == original_state
            assert db.scalar(select(Record.value).where(
                Record.key == store._key(other))) is None
        assert store.verify_audit_head(account)
        assert store.load(account)["emergency_latched"] is False

        # Restore the original synthetic primary key: the same transition
        # must succeed without a poisoned revision or ghost audit receipt.
        with factory.begin() as db:
            db.execute(update(Audit).where(
                Audit.id == risk._MAX_AUDIT_ID
            ).values(id=original_id))
        assert attempt() is True
        assert store.verify_audit_head(account)
        if operation == "initialize":
            assert store.verify_audit_head(other)
        if operation == "emergency_kill":
            assert store.load(account)["emergency_latched"] is True
    finally:
        engine.dispose()
