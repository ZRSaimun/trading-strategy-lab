"""SQLite-only nonadjacent PAPER risk audit census regressions."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Audit, Base
from app.paper_risk_reservations import PaperRiskReservationStore


@pytest.mark.parametrize("tamper", ["missing_init", "missing_policy", "extra_old"])
def test_old_receipt_census_quarantines_reservations(tmp_path, tamper):
    engine = create_engine("sqlite:///" + str(tmp_path / "census.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    s = PaperRiskReservationStore(factory)
    try:
        assert s.initialize("paper-acct-0001")
        assert s.set_policy("paper-acct-0001", 0, limit_cash="100",
                            kill_switch=False, owner_reviewed=True)
        assert s.reserve("paper-acct-0001", 1,
                         client_order_id="order-00001", risk_cash="25")
        assert s.reserve("paper-acct-0001", 2,
                         client_order_id="order-00002", risk_cash="10")
        assert s.initialize("paper-acct-0002")
        original = s.load("paper-acct-0001")
        assert original["audit_head_verified"]
        account_hash = s._key("paper-acct-0001").split(":", 1)[1]
        with factory.begin() as db:
            rows = db.scalars(select(Audit).where(
                Audit.detail.like('%"account_hash":"' + account_hash + '"%')
            ).order_by(Audit.id.asc())).all()
            assert len(rows) == 4
            if tamper == "missing_init":
                db.delete(rows[0])
            elif tamper == "missing_policy":
                db.delete(rows[1])
            else:
                db.add(Audit(id=-1, time=rows[0].time, actor=rows[0].actor,
                             action=rows[0].action, detail=rows[0].detail))
        with factory() as db:
            before = len(db.scalars(select(Audit)).all())
        assert s.load("paper-acct-0001") == {
            **original, "audit_head_verified": False,
            "reservable_risk_capacity_cash": "0",
        }
        assert not s.verify_audit_head("paper-acct-0001")
        assert s.verify_audit_head("paper-acct-0002")
        for attempt in (
            lambda: s.reserve("paper-acct-0001", 3,
                              client_order_id="order-00003", risk_cash="1"),
            lambda: s.set_policy("paper-acct-0001", 3, limit_cash="100",
                                 kill_switch=True, owner_reviewed=True),
            lambda: s.engage_kill_switch("paper-acct-0001"),
        ):
            with pytest.raises(ValueError, match="audit head"):
                attempt()
        with factory() as db:
            assert len(db.scalars(select(Audit)).all()) == before
    finally:
        engine.dispose()


def test_census_allows_interleaved_valid_accounts(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "valid.db"))
    Base.metadata.create_all(engine)
    s = PaperRiskReservationStore(sessionmaker(engine))
    try:
        for account in ("paper-acct-0001", "paper-acct-0002"):
            assert s.initialize(account)
            assert s.set_policy(account, 0, limit_cash="100",
                                kill_switch=False, owner_reviewed=True)
        assert s.reserve("paper-acct-0001", 1,
                         client_order_id="order-00001", risk_cash="0.00000001")
        assert s.reserve("paper-acct-0002", 1,
                         client_order_id="order-00002", risk_cash="5")
        assert s.verify_audit_head("paper-acct-0001")
        assert s.verify_audit_head("paper-acct-0002")
    finally:
        engine.dispose()


@pytest.mark.parametrize("tamper", [
    "duplicate_early_revision", "swap_early_revisions",
    "foreign_early_actor", "oversized_early_receipt",
    "old_bad_cash", "old_bool_count", "old_malformed_digest",
    "old_unexpected_order", "old_inconsistent_stop", "old_zero_cap_enabled",
])
def test_count_preserving_old_receipt_tampering_quarantines_account(tmp_path, tamper):
    """An unchanged receipt count and valid last two rows are not enough."""
    engine = create_engine("sqlite:///" + str(tmp_path / "sequence.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    s = PaperRiskReservationStore(factory)
    try:
        assert s.initialize("paper-acct-0001")
        assert s.set_policy("paper-acct-0001", 0, limit_cash="100",
                            kill_switch=False, owner_reviewed=True)
        assert s.reserve("paper-acct-0001", 1,
                         client_order_id="order-00001", risk_cash="25")
        assert s.reserve("paper-acct-0001", 2,
                         client_order_id="order-00002", risk_cash="10")
        assert s.initialize("paper-acct-0002")
        good = s.load("paper-acct-0001")
        assert good["audit_head_verified"]
        account_hash = s._key("paper-acct-0001").split(":", 1)[1]
        with factory.begin() as db:
            rows = db.scalars(select(Audit).where(
                Audit.detail.like('%"account_hash":"' + account_hash + '"%')
            ).order_by(Audit.id.asc())).all()
            assert len(rows) == 4
            if tamper == "duplicate_early_revision":
                rows[0].detail = rows[1].detail
            elif tamper == "swap_early_revisions":
                rows[0].detail, rows[1].detail = rows[1].detail, rows[0].detail
            elif tamper == "foreign_early_actor":
                rows[1].actor = "untrusted-audit-writer"
            elif tamper == "oversized_early_receipt":
                rows[1].detail += " " * 4097
            else:
                entry = json.loads(rows[1].detail)
                if tamper == "old_bad_cash":
                    entry["reserved_cash"] = "NaN"
                elif tamper == "old_bool_count":
                    entry["reservation_count"] = True
                elif tamper == "old_malformed_digest":
                    entry["state_sha256"] = "not-a-sha256"
                elif tamper == "old_unexpected_order":
                    entry["reservation_order_hash"] = "a" * 64
                elif tamper == "old_inconsistent_stop":
                    entry["emergency_latched"] = True
                elif tamper == "old_zero_cap_enabled":
                    entry["limit_cash"] = "0"
                rows[1].detail = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        with factory() as db:
            count_before = len(db.scalars(select(Audit)).all())
        assert s.load("paper-acct-0001") == {
            **good, "audit_head_verified": False,
            "reservable_risk_capacity_cash": "0",
        }
        assert not s.verify_audit_head("paper-acct-0001")
        assert s.verify_audit_head("paper-acct-0002")
        for attempt in (
            lambda: s.reserve("paper-acct-0001", 3,
                              client_order_id="order-00003", risk_cash="1"),
            lambda: s.set_policy("paper-acct-0001", 3, limit_cash="100",
                                 kill_switch=True, owner_reviewed=True),
            lambda: s.engage_kill_switch("paper-acct-0001"),
        ):
            with pytest.raises(ValueError, match="audit head"):
                attempt()
        with factory() as db:
            assert len(db.scalars(select(Audit)).all()) == count_before
    finally:
        engine.dispose()
