"""Bound audit receipt materialization before parsing untrusted account history."""
import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


def test_oversized_account_audit_is_rejected_before_python_materialization(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "audit-size-preflight.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.set_policy(account, 0, limit_cash="100", kill_switch=False,
                                owner_reviewed=True)
        assert store.initialize(other)
        assert store.verify_audit_head(account)
        assert store.verify_audit_head(other)
        account_hash = store._key(account).split(":", 1)[1]
        oversized = json.dumps(
            {"account_hash": account_hash, "padding": "x" * (1024 * 1024)},
            sort_keys=True, separators=(",", ":"),
        )
        with factory.begin() as db:
            receipt = db.scalar(select(Audit).where(Audit.action == "paper.risk.cas"))
            assert receipt is not None
            receipt.detail = oversized
        with factory() as db:
            before = len(db.scalars(select(Audit.id)).all())

        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select") and "audit" in statement.lower():
                statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            # This fails on the old implementation: it fetched audit.detail and
            # invoked the JSON parser before recognizing the oversized row.
            with monkeypatch.context() as patch:
                def should_not_parse(_raw):
                    raise AssertionError("oversized receipt reached Python JSON parser")
                patch.setattr(risk, "_audit_json", should_not_parse)
                snapshot = store.load(account)
                assert snapshot["audit_head_verified"] is False
                assert snapshot["reservable_risk_capacity_cash"] == "0"
                assert store.verify_audit_head(account) is False
                with pytest.raises(ValueError, match="audit head"):
                    store.reserve(account, 1, client_order_id="order-00001", risk_cash="1")
                with pytest.raises(ValueError, match="audit head"):
                    store.set_policy(account, 1, limit_cash="100", kill_switch=True,
                                     owner_reviewed=True)
                with pytest.raises(ValueError, match="audit head"):
                    store.engage_kill_switch(account)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert statements
        assert any("length(" in statement and "audit.detail" in statement and "blob" in statement for statement in statements)
        # Only the bounded SQL projection is allowed; do not load Audit ORM rows.
        assert all("audit.time" not in statement for statement in statements)
        with factory() as db:
            assert len(db.scalars(select(Audit.id)).all()) == before
        assert store.verify_audit_head(other)
        assert store.load(other)["audit_head_verified"] is True
    finally:
        engine.dispose()


def test_utf8_bytes_remain_bounded_after_sql_octet_preflight(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "audit-utf8-preflight.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    try:
        assert store.initialize("paper-acct-0001")
        account_hash = store._key("paper-acct-0001").split(":", 1)[1]
        # SQL byte length must reject this before fetching/parsing the receipt;
        # the independent Python byte check remains defense in depth.
        unicode_detail = json.dumps(
            {"account_hash": account_hash, "padding": "é" * 3000},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        assert len(unicode_detail) < risk._MAX_AUDIT_DETAIL_BYTES
        assert len(unicode_detail.encode("utf-8")) > risk._MAX_AUDIT_DETAIL_BYTES
        with factory.begin() as db:
            receipt = db.scalar(select(Audit).where(Audit.action == "paper.risk.init"))
            receipt.detail = unicode_detail
        snapshot = store.load("paper-acct-0001")
        assert snapshot["audit_head_verified"] is False
        assert snapshot["reservable_risk_capacity_cash"] == "0"
        assert not store.verify_audit_head("paper-acct-0001")
    finally:
        engine.dispose()
