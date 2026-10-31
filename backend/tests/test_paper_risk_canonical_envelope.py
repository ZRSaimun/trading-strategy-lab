"""PAPER-only persisted account-envelope byte-integrity regressions."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base, Record
from app.paper_risk_reservations import PaperRiskReservationStore


@pytest.fixture
def factory(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "canonical-envelope.db"))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [0, 2])
@pytest.mark.parametrize("mutation", ["whitespace", "escaped_key", "key_order"])
def test_noncanonical_account_envelope_fails_closed(factory, revision, mutation):
    """A byte rewrite is invalid even when the parsed state/hash are unchanged."""
    store = PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    assert store.initialize(account)
    if revision == 2:
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="0.00000001")
    assert store.initialize(other)
    assert store.load(account)["audit_head_verified"] is True
    assert store.verify_audit_head(other)
    key = store._key(account)
    with factory.begin() as db:
        row = db.get(Record, key)
        original = row.value
        if mutation == "whitespace":
            changed = "{ " + original[1:]
        elif mutation == "escaped_key":
            changed = original.replace('"account_hash"', r'"\u0061ccount_hash"', 1)
        else:
            changed = json.dumps(dict(reversed(list(json.loads(original).items()))),
                                 separators=(",", ":"))
        assert changed != original
        assert json.loads(changed) == json.loads(original)
        row.value = changed
    with factory() as db:
        audit_count = len(db.scalars(select(Audit)).all())
    for attempt in (
        lambda: store.load(account),
        lambda: store.verify_audit_head(account),
        lambda: store.reserve(account, revision, client_order_id="order-00002",
                              risk_cash="1"),
        lambda: store.set_policy(account, revision, limit_cash="100",
                                 kill_switch=True, owner_reviewed=True),
        lambda: store.engage_kill_switch(account),
    ):
        with pytest.raises(ValueError, match="corrupt"):
            attempt()
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_count
    assert store.verify_audit_head(other)
    assert store.load(other)["audit_head_verified"] is True


def test_canonical_envelope_accepts_restart_precision_and_emergency(factory):
    store = PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    assert store.initialize(account)
    assert store.set_policy(account, 0, limit_cash="100.00000001",
                            kill_switch=False, owner_reviewed=True)
    assert store.reserve(account, 1, client_order_id="order-00001",
                         risk_cash="0.00000001")
    restarted = PaperRiskReservationStore(factory)
    assert restarted.verify_audit_head(account)
    assert restarted.load(account)["reservable_risk_capacity_cash"] == "100.00000000"
    assert restarted.engage_kill_switch(account)
    final = PaperRiskReservationStore(factory).load(account)
    assert final["audit_head_verified"] is True
    assert final["emergency_latched"] is True
    assert final["reservable_risk_capacity_cash"] == "0"
    assert final["may_execute_real_order"] is False
