"""Fail-closed SQL preflight for untrusted PAPER audit actor/action metadata.

SQLite permits overlong VARCHAR values. These synthetic tests verify that
untrusted metadata is rejected in SQL before any receipt JSON is parsed.
No broker quotes, orders, or production records are involved.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


@pytest.mark.parametrize("field", ["actor", "action"])
@pytest.mark.parametrize("corruption", ["oversized", "nul_suffix"])
def test_account_audit_metadata_rejected_before_receipt_parsing(
        tmp_path, monkeypatch, field, corruption):
    engine = create_engine("sqlite:///" + str(
        tmp_path / f"metadata-{field}-{corruption}.db"))
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
            # Corrupt the *older* init receipt; the newest CAS remains valid.
            receipt = db.scalar(select(Audit).where(
                risk._account_audit_match(store._key(account))
            ).order_by(Audit.id.asc()).limit(1))
            assert receipt is not None
            original = getattr(receipt, field)
            if corruption == "oversized":
                bad = "x" * (1024 * 1024)
            else:
                bad = original + "\x00" + "x" * (1024 * 1024)
            setattr(receipt, field, bad)
        with factory() as db:
            before = db.scalar(select(func.count(Audit.id)))

        with monkeypatch.context() as patch:
            def forbidden_parse(*_args, **_kwargs):
                raise AssertionError("Untrusted audit metadata reached JSON parser")
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
