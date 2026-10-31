"""Synthetic regression: a local clock rollback must not authorize new PAPER risk.

This does not authenticate timestamps, verify broker quotes, or enable orders.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


def test_clock_rollback_blocks_new_risk_but_preserves_emergency_stop(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "rollback-paper.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    try:
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: 2_000_000_000)
            assert store.initialize(account)
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
        before = store.load(account)
        with factory() as db:
            count = db.scalar(select(func.count(Audit.id)))
            raw = db.scalar(select(Record.value).where(
                Record.key == store._key(account)))
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: 1_999_999_999)
            with pytest.raises(ValueError, match="audit clock moved backward"):
                store.reserve(account, 1, client_order_id="order-00001",
                              risk_cash="10")
            with pytest.raises(ValueError, match="audit clock moved backward"):
                store.set_policy(account, 1, limit_cash="90",
                                 kill_switch=False, owner_reviewed=True)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == count
            assert db.scalar(select(Record.value).where(
                Record.key == store._key(account))) == raw
        assert store.load(account) == before
        # Emergency stop must still persist during the same clock incident.
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: 1_999_999_999)
            assert store.engage_kill_switch(account)
        snapshot = risk.PaperRiskReservationStore(factory).load(account)
        assert snapshot["kill_switch"] is True
        assert snapshot["emergency_latched"] is True
        assert snapshot["audit_head_verified"] is True
        assert snapshot["reservable_risk_capacity_cash"] == "0"
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == count + 1
        assert store.engage_kill_switch(account)
    finally:
        engine.dispose()


def test_equal_epoch_allowed_and_clock_rollback_is_account_local(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "equal-clock-paper.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    a, b = "paper-acct-0001", "paper-acct-0002"
    try:
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: 2_000_000_000)
            assert store.initialize(a)
            assert store.set_policy(a, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
            assert store.reserve(a, 1, client_order_id="order-00001",
                                 risk_cash="10")
        with monkeypatch.context() as patch:
            patch.setattr(risk.time, "time", lambda: 1_999_999_999)
            # Another account has no later checkpoint and remains independent.
            assert store.initialize(b)
            assert store.set_policy(b, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
            assert store.reserve(b, 1, client_order_id="order-00002",
                                 risk_cash="10")
            with pytest.raises(ValueError, match="audit clock moved backward"):
                store.reserve(a, 2, client_order_id="order-00003",
                              risk_cash="10")
        restarted = risk.PaperRiskReservationStore(factory)
        assert restarted.verify_audit_head(a)
        assert restarted.verify_audit_head(b)
        assert restarted.load(a)["reservation_count"] == 1
        assert restarted.load(b)["reservation_count"] == 1
    finally:
        engine.dispose()
