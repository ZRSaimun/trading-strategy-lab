"""Offline, read-only preflight for the disconnected Twelve Data credit ledger.

Never provisions a budget, reserves credits, contacts a provider or approves data rights.
The immutable SQLite snapshot is only safe to inspect while the owner has stopped
all writers; WAL/journal sidecars are rejected instead of silently ignored.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import quote

_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_DB_BYTES = 32_000_000
_MAX_POLICIES = 3660


class CreditLedgerAuditError(ValueError):
    """Sanitized denial: never expose a local path or evidence contents."""


def _check_day(value: str) -> str:
    if not isinstance(value, str) or _DAY.fullmatch(value) is None:
        raise CreditLedgerAuditError("Invalid UTC audit day")
    try:
        if datetime.strptime(value, "%Y-%m-%d").date().isoformat() != value:
            raise ValueError()
    except ValueError:
        raise CreditLedgerAuditError("Invalid UTC audit day") from None
    return value


def _check_file(path: Path, max_bytes: int) -> int:
    try:
        uid = os.getuid()
        parent = os.lstat(path.parent)
        item = os.lstat(path)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid
                or parent.st_mode & 0o077 or not stat.S_ISREG(item.st_mode)
                or item.st_uid != uid or item.st_nlink != 1
                or item.st_mode & 0o077 or not 0 < item.st_size <= max_bytes):
            raise CreditLedgerAuditError("Private bounded ledger required")
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(path) + suffix)
            try:
                os.lstat(sidecar)
            except FileNotFoundError:
                continue
            raise CreditLedgerAuditError("Ledger must be quiescent without journal sidecars")
        return item.st_size
    except OSError:
        raise CreditLedgerAuditError("Cannot verify private ledger snapshot") from None


def _fingerprint(path: Path, max_bytes: int) -> tuple[int, str]:
    """Hash only bounded regular-file bytes, rejecting a replaced inode."""
    expected_size = _check_file(path, max_bytes)
    digest = hashlib.sha256()
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            item = os.fstat(fd)
            if (not stat.S_ISREG(item.st_mode) or item.st_nlink != 1
                    or item.st_uid != os.getuid() or item.st_mode & 0o077
                    or item.st_size != expected_size):
                raise CreditLedgerAuditError("Ledger changed during preflight")
            consumed = 0
            while chunk := os.read(fd, min(1024 * 1024, max_bytes - consumed + 1)):
                consumed += len(chunk)
                if consumed > max_bytes:
                    raise CreditLedgerAuditError("Ledger exceeds audit byte limit")
                digest.update(chunk)
            if consumed != expected_size or os.fstat(fd).st_size != expected_size:
                raise CreditLedgerAuditError("Ledger changed during preflight")
        finally:
            os.close(fd)
    except OSError:
        raise CreditLedgerAuditError("Cannot fingerprint ledger snapshot") from None
    return consumed, digest.hexdigest()


def audit_provider_credit_ledger(
    db_path: str, *, utc_day: str, max_db_bytes: int = _MAX_DB_BYTES,
) -> dict:
    """Review an owner-quiesced SQLite ledger without modifying it.

    This is an internal accounting consistency check, NOT provider billing,
    authorization, entitlement, or legal-rights verification. No secrets or
    request IDs are returned. Deny unexpected schema, corruption, overspend,
    malformed rows, future reservations, and changes during the scan.
    """
    day = _check_day(utc_day)
    if type(max_db_bytes) is not int or not 4096 <= max_db_bytes <= _MAX_DB_BYTES:
        raise CreditLedgerAuditError("Invalid audit byte limit")
    if not isinstance(db_path, str) or not 1 <= len(db_path) <= 1024:
        raise CreditLedgerAuditError("Invalid ledger location")
    path = Path(db_path)
    if not path.is_absolute():
        raise CreditLedgerAuditError("Invalid ledger location")
    size, fingerprint = _fingerprint(path, max_db_bytes)
    now = int(time.time())
    if not 60 <= now <= 253402300799:
        raise CreditLedgerAuditError("Invalid server UTC clock")
    try:
        uri = "file:" + quote(str(path), safe="/") + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            schema = set(conn.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table','view','trigger')"
            ))
            if schema != {("daily_policy", "table"), ("credit_reservation", "table")}:
                raise CreditLedgerAuditError("Unexpected credit-ledger schema")
            if conn.execute("PRAGMA integrity_check(1)").fetchone() != ("ok",):
                raise CreditLedgerAuditError("Credit-ledger integrity check failed")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise CreditLedgerAuditError("Credit-ledger orphan reservation")
            policies = conn.execute(
                "SELECT utc_day, provider, symbol, purpose, max_credits, "
                "entitlement_evidence_sha256, rights_evidence_sha256 FROM daily_policy "
                "ORDER BY utc_day LIMIT ?", (_MAX_POLICIES + 1,),
            ).fetchall()
            if len(policies) > _MAX_POLICIES:
                raise CreditLedgerAuditError("Too many credit policies to audit")
            caps = {}
            for policy in policies:
                pday, provider, symbol, purpose, cap, entitlement, rights = policy
                _check_day(pday)
                if (provider != "twelvedata" or symbol != "XAU/USD"
                        or purpose != "completed-m1-review" or type(cap) is not int
                        or not 1 <= cap <= 5000 or not isinstance(entitlement, str)
                        or _HEX64.fullmatch(entitlement) is None or not isinstance(rights, str)
                        or _HEX64.fullmatch(rights) is None or pday in caps):
                    raise CreditLedgerAuditError("Invalid credit policy")
                caps[pday] = cap
            # A bounded ledger can still contain many rows; stream rather than
            # loading identities or evidence into memory or the audit report.
            used = {pday: 0 for pday in caps}
            last_reservation_at = None
            cursor = conn.execute(
                "SELECT request_id, utc_day, manifest_sha256, reserved_at_utc, cost "
                "FROM credit_reservation ORDER BY reserved_at_utc, request_id"
            )
            for request_id, rday, manifest, stamp, cost in cursor:
                if (not isinstance(request_id, str) or _HEX32.fullmatch(request_id) is None
                        or rday not in caps or not isinstance(manifest, str)
                        or _HEX64.fullmatch(manifest) is None or type(stamp) is not int
                        or not 60 <= stamp <= now or type(cost) is not int or cost != 1):
                    raise CreditLedgerAuditError("Invalid credit reservation")
                try:
                    stamp_day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
                except (OverflowError, OSError, ValueError):
                    raise CreditLedgerAuditError("Invalid credit reservation time") from None
                if stamp_day != rday:
                    raise CreditLedgerAuditError("Reservation timestamp/day mismatch")
                # The live reservation gate requires a rolling 60-second
                # separation, not merely different UTC calendar minutes.
                # Sorting by timestamp makes any violating pair adjacent,
                # including across UTC midnight and daily policy boundaries.
                if (last_reservation_at is not None
                        and stamp - last_reservation_at < 60):
                    raise CreditLedgerAuditError("Reservations less than 60 seconds apart")
                last_reservation_at = stamp
                used[rday] += 1
                if used[rday] > caps[rday]:
                    raise CreditLedgerAuditError("Credit reservation exceeds daily cap")
            selected_cap = caps.get(day)
            selected_used = used.get(day, 0)
    except CreditLedgerAuditError:
        raise
    except (sqlite3.Error, OSError, TypeError, ValueError):
        raise CreditLedgerAuditError("Unable to audit credit-ledger snapshot") from None
    if _fingerprint(path, max_db_bytes) != (size, fingerprint):
        raise CreditLedgerAuditError("Ledger changed during audit")
    return {
        "status": "CONSISTENT_OFFLINE_ONLY" if selected_cap is not None else "NO_POLICY_FOR_DAY",
        "utc_day": day,
        "daily_credit_cap": selected_cap,
        "reserved_credits": selected_used,
        "remaining_local_allowance": selected_cap - selected_used if selected_cap is not None else None,
        "policy_days_audited": len(caps),
        "ledger_size_bytes": size,
        "ledger_sha256": fingerprint,
        "read_only": True,
        "provider_billing_reconciled": False,
        "provider_entitlement_verified": False,
        "data_rights_verified": False,
        "live_feed_activated": False,
        "may_execute_order": False,
    }
