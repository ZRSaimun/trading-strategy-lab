"""Fail closed on unknown same-account PAPER audit actions."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base
from app.paper_risk_reservations import PaperRiskReservationStore


@pytest.mark.parametrize(("action", "placement"), [
    ("paper.risk.shadow", "latest"),
    ("paper.risk.shadow", "before_init"),
    ("unrecognized.account.audit", "latest"),
])
def test_unknown_account_action_quarantines_paper_capacity(tmp_path, action, placement):
    engine = create_engine("sqlite:///" + str(tmp_path / "unknown-audit.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 1, client_order_id="order-00001", risk_cash="25")
        assert store.initialize(other)
        original = store.load(account)
        assert original["audit_head_verified"] is True
        assert original["reservable_risk_capacity_cash"] == "75"
        account_hash = store._key(account).split(":", 1)[1]
        with factory.begin() as db:
            fields = {
                "time": 0, "actor": "untrusted-writer", "action": action,
                "detail": json.dumps(
                    {"account_hash": account_hash, "operation": "shadow", "revision": 99},
                    sort_keys=True, separators=(",", ":")),
            }
            if placement == "before_init":
                fields["id"] = -1
            db.add(Audit(**fields))
        with factory() as db:
            before = len(db.scalars(select(Audit)).all())

        assert store.load(account) == {
            **original, "audit_head_verified": False,
            "reservable_risk_capacity_cash": "0",
        }
        assert not store.verify_audit_head(account)
        for attempt in (
            lambda: store.reserve(account, 2, client_order_id="order-00002",
                                  risk_cash="1"),
            lambda: store.set_policy(account, 2, limit_cash="100",
                                     kill_switch=True, owner_reviewed=True),
            lambda: store.engage_kill_switch(account),
        ):
            with pytest.raises(ValueError, match="audit head"):
                attempt()
        with factory() as db:
            assert len(db.scalars(select(Audit)).all()) == before
        assert store.verify_audit_head(other)
        assert store.load(other)["audit_head_verified"] is True
    finally:
        engine.dispose()
