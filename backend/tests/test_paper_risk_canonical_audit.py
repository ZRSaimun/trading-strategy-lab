"""Synthetic SQLite audit-encoding integrity regressions; PAPER only, no orders."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base
from app.paper_risk_reservations import PaperRiskReservationStore


@pytest.fixture
def factory(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "canonical-audit.db"))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [1, 4])
@pytest.mark.parametrize("mutation", ["whitespace", "escaped_key", "key_order"])
def test_noncanonical_retained_receipt_fails_closed(factory, revision, mutation):
    """Equivalent JSON is not the exact canonical receipt the store committed."""
    store = PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    assert store.initialize(account)
    assert store.set_policy(account, 0, limit_cash="100", kill_switch=False,
                            owner_reviewed=True)
    assert store.reserve(account, 1, client_order_id="order-00001", risk_cash="25")
    assert store.set_policy(account, 2, limit_cash="150", kill_switch=False,
                            owner_reviewed=True)
    assert store.reserve(account, 3, client_order_id="order-00002", risk_cash="10")
    assert store.initialize(other)
    good = store.load(account)
    assert good["audit_head_verified"] is True

    account_hash = store._key(account).split(":", 1)[1]
    with factory.begin() as db:
        rows = db.scalars(select(Audit).where(
            Audit.detail.like('%"account_hash":"' + account_hash + '"%')
        ).order_by(Audit.id.asc())).all()
        target = next(row for row in rows
                      if json.loads(row.detail)["revision"] == revision)
        original = target.detail
        if mutation == "whitespace":
            changed = "{ " + original[1:]
        elif mutation == "escaped_key":
            changed = original.replace('"operation"', r'"\u006fperation"', 1)
        else:
            changed = json.dumps(dict(reversed(list(json.loads(original).items()))),
                                 separators=(",", ":"))
        assert changed != original
        assert json.loads(changed) == json.loads(original)
        target.detail = changed

    with factory() as db:
        audit_count = len(db.scalars(select(Audit)).all())
    snapshot = store.load(account)
    assert snapshot == {
        **good,
        "audit_head_verified": False,
        "reservable_risk_capacity_cash": "0",
    }
    assert not store.verify_audit_head(account)
    assert store.verify_audit_head(other)
    for attempt in (
        lambda: store.reserve(account, 4, client_order_id="order-00003", risk_cash="1"),
        lambda: store.set_policy(account, 4, limit_cash="150", kill_switch=True,
                                 owner_reviewed=True),
        lambda: store.engage_kill_switch(account),
    ):
        with pytest.raises(ValueError, match="audit head"):
            attempt()
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_count


def test_store_generated_canonical_receipts_survive_restart_and_emergency(factory):
    account = "paper-acct-0001"
    store = PaperRiskReservationStore(factory)
    assert store.initialize(account)
    assert store.set_policy(account, 0, limit_cash="100.00000001",
                            kill_switch=False, owner_reviewed=True)
    assert store.reserve(account, 1, client_order_id="order-00001",
                         risk_cash="0.00000001")
    with factory() as db:
        receipts = db.scalars(select(Audit).order_by(Audit.id.asc())).all()
        assert len(receipts) == 3
        for receipt in receipts:
            assert receipt.detail == json.dumps(json.loads(receipt.detail),
                                                sort_keys=True, separators=(",", ":"),
                                                allow_nan=False)
    restarted = PaperRiskReservationStore(factory)
    assert restarted.verify_audit_head(account)
    assert restarted.engage_kill_switch(account)
    snapshot = PaperRiskReservationStore(factory).load(account)
    assert snapshot["audit_head_verified"] is True
    assert snapshot["emergency_latched"] is True
    assert snapshot["reservable_risk_capacity_cash"] == "0"
    assert snapshot["may_execute_paper_order"] is False
    assert snapshot["may_execute_real_order"] is False
