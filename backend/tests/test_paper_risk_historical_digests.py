"""Synthetic SQLite checks for historical PAPER risk audit digests; no orders."""
import json
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Audit, Base
from app.paper_risk_reservations import PaperRiskReservationStore


@pytest.fixture
def factory(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "risk-history.db"))
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


def prepared(factory):
    s = PaperRiskReservationStore(factory)
    assert s.initialize("paper-acct-0001")
    assert s.set_policy("paper-acct-0001", 0, limit_cash="100.00",
                        kill_switch=False, owner_reviewed=True)
    assert s.reserve("paper-acct-0001", 1,
                     client_order_id="order-00001", risk_cash="25")
    assert s.set_policy("paper-acct-0001", 2, limit_cash="150.00",
                        kill_switch=False, owner_reviewed=True)
    assert s.reserve("paper-acct-0001", 3,
                     client_order_id="order-00002", risk_cash="0.00000001")
    assert s.set_policy("paper-acct-0001", 4, limit_cash="150.00",
                        kill_switch=True, owner_reviewed=True)
    return s


@pytest.mark.parametrize("old_revision", [1, 2, 3])
def test_old_plausible_digest_fails_closed(factory, old_revision):
    """A forged old checksum cannot hide behind intact latest checkpoints."""
    s = prepared(factory)
    assert s.initialize("paper-acct-0002")
    before = s.load("paper-acct-0001")
    assert before["audit_head_verified"] is True
    account_hash = s._key("paper-acct-0001").split(":", 1)[1]
    with factory.begin() as db:
        rows = db.scalars(select(Audit).where(
            Audit.detail.like('%"account_hash":"' + account_hash + '"%')
        ).order_by(Audit.id.asc())).all()
        row = next(r for r in rows if json.loads(r.detail)["revision"] == old_revision)
        detail = json.loads(row.detail)
        assert detail["state_sha256"] != "0" * 64
        detail["state_sha256"] = "0" * 64
        row.detail = json.dumps(detail, sort_keys=True, separators=(",", ":"))
    with factory() as db:
        count = len(db.scalars(select(Audit)).all())
    assert s.load("paper-acct-0001") == {
        **before, "audit_head_verified": False,
        "reservable_risk_capacity_cash": "0",
    }
    assert not s.verify_audit_head("paper-acct-0001")
    assert s.verify_audit_head("paper-acct-0002")
    for attempt in (
        lambda: s.reserve("paper-acct-0001", 5,
                          client_order_id="order-00003", risk_cash="1"),
        lambda: s.set_policy("paper-acct-0001", 5, limit_cash="150.00",
                             kill_switch=True, owner_reviewed=True),
        lambda: s.engage_kill_switch("paper-acct-0001"),
    ):
        with pytest.raises(ValueError, match="audit head"):
            attempt()
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == count


def test_historical_digests_accept_precision_restart_and_emergency(factory):
    s = PaperRiskReservationStore(factory)
    assert s.initialize("paper-acct-0001")
    assert s.set_policy("paper-acct-0001", 0, limit_cash="100.00",
                        kill_switch=False, owner_reviewed=True)
    assert s.reserve("paper-acct-0001", 1,
                     client_order_id="order-00001", risk_cash="0.00000001")
    assert s.set_policy("paper-acct-0001", 2, limit_cash="150.00",
                        kill_switch=True, owner_reviewed=True)
    assert PaperRiskReservationStore(factory).verify_audit_head("paper-acct-0001")
    assert s.set_policy("paper-acct-0001", 3, limit_cash="150.00",
                        kill_switch=False, owner_reviewed=True)
    assert s.reserve("paper-acct-0001", 4,
                     client_order_id="order-00002", risk_cash="0.00000002")
    assert PaperRiskReservationStore(factory).verify_audit_head("paper-acct-0001")
    assert s.engage_kill_switch("paper-acct-0001")
    snapshot = PaperRiskReservationStore(factory).load("paper-acct-0001")
    assert snapshot["audit_head_verified"] is True
    assert snapshot["reserved_cash"] == "3E-8"
    assert snapshot["reservable_risk_capacity_cash"] == "0"
