"""Synthetic offline audit tests. Never contacts a market-data provider."""
from datetime import datetime, timezone
import hashlib
import sqlite3

import pytest

from app.provider_credit_ledger_audit import (
    CreditLedgerAuditError, audit_provider_credit_ledger,
)

DAY = "2026-10-26"
STAMP = int(datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc).timestamp())
SCHEMA = """
CREATE TABLE daily_policy (
 utc_day TEXT PRIMARY KEY,
 provider TEXT NOT NULL CHECK(provider='twelvedata'),
 symbol TEXT NOT NULL CHECK(symbol='XAU/USD'),
 purpose TEXT NOT NULL CHECK(purpose='completed-m1-review'),
 max_credits INTEGER NOT NULL CHECK(max_credits BETWEEN 1 AND 5000),
 entitlement_evidence_sha256 TEXT NOT NULL,
 rights_evidence_sha256 TEXT NOT NULL
);
CREATE TABLE credit_reservation (
 request_id TEXT PRIMARY KEY,
 utc_day TEXT NOT NULL REFERENCES daily_policy(utc_day),
 manifest_sha256 TEXT NOT NULL,
 reserved_at_utc INTEGER NOT NULL,
 cost INTEGER NOT NULL CHECK(cost=1)
);
"""


def ledger(tmp_path, *, cap=2, rows=1):
    path = tmp_path / "ledger.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO daily_policy VALUES (?,?,?,?,?,?,?)",
                   (DAY, "twelvedata", "XAU/USD", "completed-m1-review", cap,
                    "a"*64, "b"*64))
        for i in range(rows):
            db.execute("INSERT INTO credit_reservation VALUES (?,?,?,?,?)",
                       (f"{i:032x}", DAY, "c"*64, STAMP + i * 60, 1))
    path.chmod(0o600)
    return path


def audit(path, **kwargs):
    return audit_provider_credit_ledger(str(path), utc_day=DAY, **kwargs)


def test_consistent_snapshot_has_no_write_and_no_sensitive_ids(tmp_path):
    path = ledger(tmp_path)
    original = path.read_bytes()
    report = audit(path)
    assert report["status"] == "CONSISTENT_OFFLINE_ONLY"
    assert report["reserved_credits"] == 1
    assert report["remaining_local_allowance"] == 1
    assert report["ledger_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["provider_entitlement_verified"] is False
    assert report["may_execute_order"] is False
    assert "a"*64 not in str(report)
    assert "c"*64 not in str(report)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("ledger.sqlite-*"))


def test_missing_policy_is_not_approval(tmp_path):
    path = ledger(tmp_path)
    report = audit_provider_credit_ledger(str(path), utc_day="2026-10-27")
    assert report["status"] == "NO_POLICY_FOR_DAY"
    assert report["daily_credit_cap"] is None
    assert report["remaining_local_allowance"] is None


def test_overspend_denied_even_if_schema_constraints_allow_it(tmp_path):
    path = ledger(tmp_path, cap=1, rows=2)
    with pytest.raises(CreditLedgerAuditError, match="exceeds"):
        audit(path)


def test_same_utc_minute_reservations_fail_offline_audit(tmp_path):
    path = ledger(tmp_path, cap=2, rows=2)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE credit_reservation SET reserved_at_utc=? WHERE request_id=?",
            (STAMP + 30, f"{1:032x}"),
        )
    with pytest.raises(CreditLedgerAuditError, match="one UTC minute"):
        audit(path)


def test_timestamp_day_mismatch_denied(tmp_path):
    path = ledger(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE credit_reservation SET reserved_at_utc=?", (STAMP - 86400,))
    with pytest.raises(CreditLedgerAuditError, match="timestamp/day"):
        audit(path)


def test_invalid_request_identity_denied(tmp_path):
    path = ledger(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE credit_reservation SET request_id='not-hex'")
    with pytest.raises(CreditLedgerAuditError, match="Invalid credit reservation"):
        audit(path)


def test_orphan_reservation_denied(tmp_path):
    path = ledger(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE credit_reservation SET utc_day='2026-10-25'")
    with pytest.raises(CreditLedgerAuditError, match="orphan"):
        audit(path)


def test_trigger_schema_denied(tmp_path):
    path = ledger(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER surprise AFTER INSERT ON credit_reservation BEGIN SELECT 1; END")
    with pytest.raises(CreditLedgerAuditError, match="schema"):
        audit(path)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sidecar_rejected(tmp_path, suffix):
    path = ledger(tmp_path)
    (tmp_path / (path.name + suffix)).write_bytes(b"synthetic")
    with pytest.raises(CreditLedgerAuditError, match="quiescent"):
        audit(path)


def test_world_readable_ledger_rejected(tmp_path):
    path = ledger(tmp_path)
    path.chmod(0o644)
    with pytest.raises(CreditLedgerAuditError, match="Private"):
        audit(path)


def test_symlink_rejected(tmp_path):
    path = ledger(tmp_path)
    link = tmp_path / "alias.sqlite"
    link.symlink_to(path)
    with pytest.raises(CreditLedgerAuditError, match="Private"):
        audit(link)


@pytest.mark.parametrize("bad", [0, True, 4095, 32_000_001, "10000"])
def test_invalid_budget_denied(tmp_path, bad):
    path = ledger(tmp_path)
    with pytest.raises(CreditLedgerAuditError, match="byte limit"):
        audit(path, max_db_bytes=bad)


def test_truncated_sqlite_denied(tmp_path):
    path = ledger(tmp_path)
    path.write_bytes(b"not a sqlite database")
    with pytest.raises(CreditLedgerAuditError):
        audit(path)
