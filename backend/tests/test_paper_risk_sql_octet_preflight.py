"""SQL-side UTF-8 octet preflight for disconnected PAPER risk records.

Synthetic SQLite fixtures only; no broker, live data, or execution path.
SQLite length(TEXT) stops at embedded NUL and counts code points rather than
UTF-8 bytes. The preflight must use byte length before materializing text.
"""
import pytest
from sqlalchemy import LargeBinary, cast, create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base, Record


@pytest.mark.parametrize("corruption", ["nul_suffix", "multibyte_suffix"])
def test_state_sql_byte_guard_precedes_python_decode(tmp_path, monkeypatch, corruption):
    engine = create_engine("sqlite:///" + str(tmp_path / ("state-" + corruption + ".db")))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.initialize(other)
        key = store._key(account)
        suffix = ("\x00" + "x" * (1024 * 1024)
                  if corruption == "nul_suffix" else "é" * 40000)
        with factory.begin() as db:
            record = db.get(Record, key)
            record.value += suffix
        with factory() as db:
            chars, octets = db.execute(select(
                func.length(Record.value),
                func.length(cast(Record.value, LargeBinary)),
            ).where(Record.key == key)).one()
            before = db.scalar(select(func.count(Audit.id)))
        assert chars < risk._MAX_ENVELOPE_BYTES < octets

        with monkeypatch.context() as patch:
            def forbidden_decode(*_args, **_kwargs):
                raise AssertionError("Oversized state reached Python decoder")
            patch.setattr(risk, "_decode", forbidden_decode)
            for attempt in (
                lambda: store.load(account),
                lambda: store.verify_audit_head(account),
                lambda: store.reserve(account, 0, client_order_id="order-00001",
                                      risk_cash="1"),
                lambda: store.engage_kill_switch(account),
            ):
                with pytest.raises(ValueError, match="corrupt"):
                    attempt()
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == before
        assert store.verify_audit_head(other)
    finally:
        engine.dispose()


@pytest.mark.parametrize("corruption", ["nul_suffix", "multibyte_suffix"])
def test_audit_sql_byte_guard_precedes_python_json_parse(tmp_path, monkeypatch, corruption):
    engine = create_engine("sqlite:///" + str(tmp_path / ("audit-" + corruption + ".db")))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        assert store.initialize(other)
        suffix = ("\x00" + "x" * (1024 * 1024)
                  if corruption == "nul_suffix" else "é" * 3000)
        with factory.begin() as db:
            receipt = db.scalar(select(Audit).where(Audit.action == "paper.risk.init")
                                .order_by(Audit.id).limit(1))
            assert receipt is not None
            receipt.detail += suffix
            target_id = receipt.id
        with factory() as db:
            chars, octets = db.execute(select(
                func.length(Audit.detail),
                func.length(cast(Audit.detail, LargeBinary)),
            ).where(Audit.id == target_id)).one()
            before = db.scalar(select(func.count(Audit.id)))
        assert chars < risk._MAX_AUDIT_DETAIL_BYTES < octets

        with monkeypatch.context() as patch:
            def forbidden_parse(*_args, **_kwargs):
                raise AssertionError("Oversized receipt reached Python JSON parser")
            patch.setattr(risk, "_audit_json", forbidden_parse)
            snapshot = store.load(account)
            assert snapshot["audit_head_verified"] is False
            assert snapshot["reservable_risk_capacity_cash"] == "0"
            assert store.verify_audit_head(account) is False
            with pytest.raises(ValueError, match="audit head"):
                store.set_policy(account, 0, limit_cash="100",
                                 kill_switch=False, owner_reviewed=True)
            with pytest.raises(ValueError, match="audit head"):
                store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == before
        assert store.verify_audit_head(other)
    finally:
        engine.dispose()
