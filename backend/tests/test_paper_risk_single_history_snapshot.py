"""The PAPER audit head and predecessor must come from one bounded history read.

Synthetic SQLite only. A single SQL statement narrows intra-verification
read skew; it does NOT guarantee serializable isolation or trusted receipts.
"""
import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


@pytest.mark.parametrize("terminal", ["initialize", "policy", "reserve", "emergency"])
def test_head_and_predecessor_use_same_ordered_history_query(tmp_path, terminal):
    engine = create_engine("sqlite:///" + str(tmp_path / f"{terminal}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    observed = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _many):
        if "ORDER BY audit.id" in statement:
            observed.append(statement)

    try:
        assert store.initialize(account)
        if terminal in ("policy", "reserve", "emergency"):
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
        if terminal in ("reserve", "emergency"):
            assert store.reserve(account, 1, client_order_id="order-00001",
                                 risk_cash="10")
        if terminal == "emergency":
            assert store.engage_kill_switch(account)

        with factory() as db:
            key = store._key(account)
            raw = risk._read_bounded_state(db, key)
            state, reserved = risk._decode(raw, key=key)
            event.listen(engine, "before_cursor_execute", record_query)
            try:
                assert risk._audit_head_matches(db, key, raw, state, reserved)
            finally:
                event.remove(engine, "before_cursor_execute", record_query)
        assert len(observed) == 1, "Do not read latest audit separately from history"
        assert "ORDER BY audit.id ASC" in observed[0]
        assert "LIMIT" in observed[0]
    finally:
        engine.dispose()


def test_corrupt_prior_receipt_fails_closed_with_one_history_read(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "corrupt.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account = "paper-acct-0001"
    ordered_reads = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _many):
        if "ORDER BY audit.id" in statement:
            ordered_reads.append(statement)

    try:
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert store.reserve(account, 1, client_order_id="order-00001",
                             risk_cash="10")
        with factory.begin() as db:
            key = store._key(account)
            prior = db.scalars(select(Audit).where(
                risk._account_audit_match(key)
            ).order_by(Audit.id.asc())).all()[1]
            detail = json.loads(prior.detail)
            detail["limit_cash"] = "90"
            prior.detail = json.dumps(detail, sort_keys=True, separators=(",", ":"))
        with factory() as db:
            raw = risk._read_bounded_state(db, key)
            state, reserved = risk._decode(raw, key=key)
            event.listen(engine, "before_cursor_execute", record_query)
            try:
                assert risk._audit_head_matches(db, key, raw, state, reserved) is False
            finally:
                event.remove(engine, "before_cursor_execute", record_query)
        assert len(ordered_reads) == 1
        assert store.load(account)["reservable_risk_capacity_cash"] == "0"
        with pytest.raises(ValueError, match="audit head"):
            store.reserve(account, 2, client_order_id="order-00002", risk_cash="1")
    finally:
        engine.dispose()
