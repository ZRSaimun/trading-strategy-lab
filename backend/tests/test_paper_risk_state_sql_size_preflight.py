"""Bound PAPER risk-state materialization at the SQL boundary (synthetic only)."""
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


def test_oversized_state_fails_before_python_decode_and_preserves_other_accounts(
    tmp_path, monkeypatch,
):
    engine = create_engine("sqlite:///" + str(tmp_path / "oversized-state.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.set_policy(
            account, 0, limit_cash="100", kill_switch=False, owner_reviewed=True
        )
        assert store.initialize(other)
        assert store.verify_audit_head(other)
        with factory.begin() as db:
            record = db.get(Record, store._key(account))
            record.value = record.value + (" " * (1024 * 1024))
        with factory() as db:
            before = len(db.scalars(select(Audit.id)).all())

        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select") and "record" in statement.lower():
                statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with monkeypatch.context() as patch:
                def forbidden_decode(*_args, **_kwargs):
                    raise AssertionError("oversized state reached Python decoder")
                patch.setattr(risk, "_decode", forbidden_decode)
                for attempt in (
                    lambda: store.load(account),
                    lambda: store.verify_audit_head(account),
                    lambda: store.reserve(
                        account, 1, client_order_id="order-00001", risk_cash="1"
                    ),
                    lambda: store.set_policy(
                        account, 1, limit_cash="100", kill_switch=True,
                        owner_reviewed=True,
                    ),
                    lambda: store.engage_kill_switch(account),
                ):
                    with pytest.raises(ValueError, match="corrupt"):
                        attempt()
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert statements
        assert any("case" in sql and "length(" in sql and "value" in sql for sql in statements)
        with factory() as db:
            assert len(db.scalars(select(Audit.id)).all()) == before
        assert store.verify_audit_head(other)
        assert store.load(other)["audit_head_verified"] is True
    finally:
        engine.dispose()


def test_sql_octet_limit_rejects_utf8_payload(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "utf8-state.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    try:
        assert store.initialize("paper-acct-0001")
        key = store._key("paper-acct-0001")
        with factory.begin() as db:
            record = db.get(Record, key)
            # SQL byte length must reject the payload even though its Unicode
            # character count is below 64 KiB. Python checks remain as backup.
            record.value = record.value + ("é" * 40000)
            assert len(record.value) < risk._MAX_ENVELOPE_BYTES
            assert len(record.value.encode("utf-8")) > risk._MAX_ENVELOPE_BYTES
        with factory() as db:
            before = len(db.scalars(select(Audit.id)).all())
        with pytest.raises(ValueError, match="corrupt"):
            store.load("paper-acct-0001")
        with pytest.raises(ValueError, match="corrupt"):
            store.reserve(
                "paper-acct-0001", 0, client_order_id="order-00001", risk_cash="1"
            )
        with factory() as db:
            assert len(db.scalars(select(Audit.id)).all()) == before
    finally:
        engine.dispose()
