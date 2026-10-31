"""Reject nonpositive persisted PAPER audit IDs before parsing receipts.

SQLite permits manually rewriting INTEGER PRIMARY KEY values to zero or
negative numbers. The store itself emits positive auto-generated IDs.
All rows and inputs here are synthetic, not broker-authenticated evidence.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import paper_risk_reservations as risk
from app.db import Audit, Base


@pytest.mark.parametrize("invalid_id", [0, -7])
@pytest.mark.parametrize("after_policy", [False, True])
def test_nonpositive_old_audit_id_fails_closed_before_json(
        tmp_path, monkeypatch, invalid_id, after_policy):
    engine = create_engine("sqlite:///" + str(
        tmp_path / f"nonpositive-id-{invalid_id}-{after_policy}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        if after_policy:
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
            assert store.reserve(account, 1, client_order_id="order-00001",
                                 risk_cash="10")
        assert store.initialize(other)
        assert store.verify_audit_head(account)
        assert store.verify_audit_head(other)
        revision = 2 if after_policy else 0
        with factory.begin() as db:
            oldest = db.scalar(select(Audit).where(
                risk._account_audit_match(store._key(account))
            ).order_by(Audit.id.asc()).limit(1))
            assert oldest is not None and oldest.id > 0
            # Keep all JSON, receipt count, and revision values untouched.
            # The old receipt remains first in ID order.
            oldest.id = invalid_id
        with factory() as db:
            audit_count = db.scalar(select(func.count(Audit.id)))
        with monkeypatch.context() as patch:
            def forbidden_parse(*_args, **_kwargs):
                raise AssertionError("Nonpositive audit ID reached JSON parser")
            patch.setattr(risk, "_audit_json", forbidden_parse)
            snapshot = store.load(account)
            assert snapshot["audit_head_verified"] is False
            assert snapshot["reservable_risk_capacity_cash"] == "0"
            assert store.verify_audit_head(account) is False
            with pytest.raises(ValueError, match="audit head"):
                store.set_policy(account, revision, limit_cash="100",
                                 kill_switch=False, owner_reviewed=True)
            with pytest.raises(ValueError, match="audit head"):
                store.reserve(account, revision, client_order_id="order-00002",
                              risk_cash="1")
            with pytest.raises(ValueError, match="audit head"):
                store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == audit_count
        assert store.verify_audit_head(other)
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_id", [2**31, 2**31 + 37])
@pytest.mark.parametrize("after_policy", [False, True])
def test_oversized_sqlite_audit_id_fails_closed_before_json(
        tmp_path, monkeypatch, invalid_id, after_policy):
    """SQLite ROWID can exceed PostgreSQL Audit.id's signed INT4 range."""
    engine = create_engine("sqlite:///" + str(
        tmp_path / f"oversized-id-{invalid_id}-{after_policy}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"
    try:
        assert store.initialize(account)
        if after_policy:
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
        assert store.initialize(other)
        key = store._key(account)
        assert store.verify_audit_head(account)
        with factory.begin() as db:
            # Change the newest account-local ID only. JSON, order, revision,
            # timestamps, and all account-state bytes remain unchanged.
            latest = db.scalar(select(Audit).where(
                risk._account_audit_match(key)
            ).order_by(Audit.id.desc()).limit(1))
            assert latest is not None
            latest.id = invalid_id
        with factory() as db:
            count = db.scalar(select(func.count(Audit.id)))
        with monkeypatch.context() as patch:
            def forbidden_parse(*_args, **_kwargs):
                raise AssertionError("Out-of-range audit ID reached JSON parser")
            patch.setattr(risk, "_audit_json", forbidden_parse)
            snapshot = store.load(account)
            assert snapshot["audit_head_verified"] is False
            assert snapshot["reservable_risk_capacity_cash"] == "0"
            assert store.verify_audit_head(account) is False
            with pytest.raises(ValueError, match="audit head"):
                store.set_policy(account, int(after_policy), limit_cash="110",
                                 kill_switch=False, owner_reviewed=True)
            with pytest.raises(ValueError, match="audit head"):
                store.engage_kill_switch(account)
        with factory() as db:
            assert db.scalar(select(func.count(Audit.id))) == count
        assert store.verify_audit_head(other)
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_id,after_policy", [
    (0, True),
    (risk._MAX_AUDIT_ID + 1, False),
])
def test_history_rechecks_id_when_sql_preflight_is_stale(
        tmp_path, invalid_id, after_policy):
    """A clean *earlier* SQL preflight is not proof about later history rows.

    Model a stale preflight result while keeping the actual SQLite history
    invalid. This is a deterministic read-boundary regression, not a claim
    that SQLite permits this exact interleaving under every isolation mode.
    """
    engine = create_engine("sqlite:///" + str(
        tmp_path / f"stale-id-{invalid_id}.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = risk.PaperRiskReservationStore(factory)
    account, other = "paper-acct-0001", "paper-acct-0002"

    class StaleMetadataPreflight:
        def __init__(self, session):
            self.session = session
            self.scalar_calls = 0

        def scalar(self, statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                # The first scalar() in _audit_head_matches is its invalid
                # metadata/ID SQL preflight. Simulate a previously clean read.
                return None
            return self.session.scalar(statement)

        def __getattr__(self, name):
            return getattr(self.session, name)

    try:
        assert store.initialize(account)
        if after_policy:
            assert store.set_policy(account, 0, limit_cash="100",
                                    kill_switch=False, owner_reviewed=True)
        assert store.initialize(other)
        key = store._key(account)
        with factory.begin() as db:
            oldest = db.scalar(select(Audit).where(
                risk._account_audit_match(key)
            ).order_by(Audit.id.asc()).limit(1))
            assert oldest is not None
            oldest.id = invalid_id

        with factory() as db:
            raw = risk._read_bounded_state(db, key)
            state, reserved = risk._decode(raw, key=key)
            stale = StaleMetadataPreflight(db)
            # This must fail on the *actual* ID returned by the bounded
            # history query, even though the SQL preflight was masked.
            assert risk._audit_head_matches(stale, key, raw, state, reserved) is False
            assert stale.scalar_calls >= 2

        assert store.load(account)["reservable_risk_capacity_cash"] == "0"
        assert store.verify_audit_head(other) is True
    finally:
        engine.dispose()
