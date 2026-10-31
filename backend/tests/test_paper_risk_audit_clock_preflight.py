"""Fail closed before persisting self-invalidating PAPER audit timestamps.

Synthetic SQLite only; no trusted-clock, broker, or execution evidence.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


@pytest.mark.parametrize("clock_value", [0, -1, 0.5, float("nan"), float("inf")])
def test_invalid_clock_cannot_initialize_account(tmp_path, monkeypatch, clock_value):
    engine = create_engine("sqlite:///" + str(tmp_path / "invalid-init-clock.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: clock_value)
            with pytest.raises(ValueError, match="audit clock"):
                store.initialize("paper-acct-0001")
        with factory() as db:
            assert db.scalar(select(func.count(Record.key))) == 0
            assert db.scalar(select(func.count(Audit.id))) == 0
        assert store.initialize("paper-acct-0001")
        assert store.verify_audit_head("paper-acct-0001")
    finally:
        engine.dispose()


@pytest.mark.parametrize("clock_value", [0, -1, 0.5, float("nan"), float("inf")])
def test_invalid_clock_cannot_commit_policy_reservation_or_emergency(
        tmp_path, monkeypatch, clock_value):
    engine = create_engine("sqlite:///" + str(tmp_path / "invalid-cas-clock.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.initialize(other)
        before = store.load(account)
        with factory() as db:
            count = db.scalar(select(func.count(Audit.id)))
            raw = db.scalar(select(Record.value).where(
                Record.key == store._key(account)))
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: clock_value)
            with pytest.raises(ValueError, match="audit clock"):
                store.reserve(account, 1, client_order_id="order-00001",
                              risk_cash="10")
            with pytest.raises(ValueError, match="audit clock"):
                store.set_policy(account, 1, limit_cash="90",
                                 kill_switch=False, owner_reviewed=True)
            with pytest.raises(ValueError, match="audit clock"):
                store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == count
            assert db.scalar(select(Record.value).where(
                Record.key == store._key(account))) == raw
        assert store.load(account) == before
        assert store.verify_audit_head(other)
        # Restoring a valid clock must leave the account usable for PAPER
        # accounting; no poisoned audit revision was committed.
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="10")
        assert store.verify_audit_head(account)
    finally:
        engine.dispose()
