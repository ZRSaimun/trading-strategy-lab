"""Reject malformed retained PAPER audit timestamps before JSON parsing.

All inputs are synthetic; the audit clock remains self-attested, not trusted.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


@pytest.mark.parametrize("bad_time", [-1, 0, "invalid-epoch"])
def test_invalid_old_audit_timestamp_fails_closed_before_parsing(
        tmp_path, monkeypatch, bad_time):
    engine = create_engine("sqlite:///" + str(tmp_path / "audit-time.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.initialize(other)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        with factory.begin() as db:
            receipt = db.scalar(select(Audit).where(
                risk._account_audit_match(store._key(account))
            ).order_by(Audit.id.asc()).limit(1))
            assert receipt is not None
            receipt.time = bad_time
        with factory() as db:
            before = db.scalar(select(func.count(Audit.id)))

        with monkeypatch.context() as patch:
            def forbidden_parse(*_args, **_kwargs):
                raise AssertionError("Invalid audit timestamp reached JSON parsing")
            patch.setattr(risk, "_audit_json", forbidden_parse)
            snapshot = store.load(account)
            assert snapshot["audit_head_verified"] is False
            assert snapshot["reservable_risk_capacity_cash"] == "0"
            assert store.verify_audit_head(account) is False
            with pytest.raises(ValueError, match="audit head"):
                store.reserve(account, 1, client_order_id="order-00001",
                              risk_cash="1")
            with pytest.raises(ValueError, match="audit head"):
                store.set_policy(account, 1, limit_cash="50",
                                 kill_switch=True, owner_reviewed=True)
            with pytest.raises(ValueError, match="audit head"):
                store.engage_kill_switch(account)

        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == before
        assert store.verify_audit_head(other)
    finally:
        engine.dispose()
