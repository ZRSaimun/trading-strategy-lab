"""Reject synthetic no-op policy receipts that falsely consume PAPER audit capacity.

SQLite-only internal integrity regressions; self-attested hashes are not
broker evidence, authenticated audit signatures, or trading permission.
"""
import hashlib
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


@pytest.mark.parametrize("stage", ["initial", "after_reservation"])
def test_forged_historical_noop_policy_fails_closed(tmp_path, stage):
    engine = create_engine("sqlite:///" + str(tmp_path / f"policy-{stage}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.initialize(other)
        if stage == "after_reservation":
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
            assert store.reserve(account, 1, client_order_id="order-00001",
                                 risk_cash="10")
        assert store.verify_audit_head(account)
        key = store._key(account)
        with factory.begin() as db:
            record = db.get(Record, key)
            state, _ = risk._decode(record.value, key=key)
            state["revision"] += 1
            # Simulate a rewritten checkpoint with valid self-attested hashes,
            # but an impossible policy transition: nothing actually changed.
            raw = risk._encode(state, key=key)
            record.value = raw
            reserved = sum((Decimal(value) for value in state["reservations"].values()),
                           Decimal(0))
            latest_time = db.scalar(select(func.max(Audit.time)).where(
                risk._account_audit_match(key)))
            db.add(Audit(
                time=latest_time,
                actor="paper-risk-store",
                action="paper.risk.cas",
                detail=risk._canonical({
                    "account_hash": key.split(":", 1)[1],
                    "operation": "policy",
                    "revision": state["revision"],
                    "kill_switch": state["kill_switch"],
                    "emergency_latched": state["emergency_latched"],
                    "limit_cash": state["limit_cash"],
                    "reserved_cash": str(reserved),
                    "reservation_count": len(state["reservations"]),
                    "reservation_order_hash": None,
                    "state_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }),
            ))
        with factory() as db:
            before_count = db.scalar(select(func.count(Audit.id)))
            before_raw = db.scalar(select(Record.value).where(Record.key == key))

        snapshot = risk.PaperRiskReservationStore(factory).load(account)
        assert snapshot["audit_head_verified"] is False
        assert snapshot["reservable_risk_capacity_cash"] == "0"
        assert snapshot["may_execute_paper_order"] is False
        assert snapshot["may_execute_real_order"] is False
        assert not store.verify_audit_head(account)
        assert store.verify_audit_head(other)
        with pytest.raises(ValueError, match="audit head"):
            store.set_policy(account, snapshot["revision"], limit_cash="110",
                             kill_switch=False, owner_reviewed=True)
        with pytest.raises(ValueError, match="audit head"):
            store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == before_count
            assert db.scalar(select(Record.value).where(Record.key == key)) == before_raw
    finally:
        engine.dispose()


def test_real_policy_text_revision_remains_verifiable(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "policy-text.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    try:
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.set_policy(account, 1, limit_cash="100.00",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 2, client_order_id="order-00001",
                             risk_cash="1")
        assert store.set_policy(account, 3, limit_cash="100.00",
                                kill_switch=True, owner_reviewed=True)
        restarted = risk.PaperRiskReservationStore(factory)
        assert restarted.verify_audit_head(account)
        snapshot = restarted.load(account)
        assert snapshot["audit_head_verified"] is True
        assert snapshot["limit_cash"] == "100.00"
        assert snapshot["kill_switch"] is True
        assert snapshot["may_execute_paper_order"] is False
    finally:
        engine.dispose()
