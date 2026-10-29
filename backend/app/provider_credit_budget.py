"""Opt-in, durable, fail-closed *reservation* of potential Twelve Data API credits.

No vendor calls, secrets, routes, polling, entitlement attestation or refunds.
A reservation consumes a locally budgeted credit even if the HTTP call fails.
The SQLite file must be on durable single-host storage; do not use ephemeral
Render filesystems or treat operator evidence hashes as verified licenses.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import quote

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST = re.compile(r"[0-9a-f]{32}\Z")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_policy (
  utc_day TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK(provider='twelvedata'),
  symbol TEXT NOT NULL CHECK(symbol='XAU/USD'),
  purpose TEXT NOT NULL CHECK(purpose='completed-m1-review'),
  max_credits INTEGER NOT NULL CHECK(max_credits BETWEEN 1 AND 5000),
  entitlement_evidence_sha256 TEXT NOT NULL,
  rights_evidence_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_reservation (
  request_id TEXT PRIMARY KEY,
  utc_day TEXT NOT NULL REFERENCES daily_policy(utc_day),
  manifest_sha256 TEXT NOT NULL,
  reserved_at_utc INTEGER NOT NULL,
  cost INTEGER NOT NULL CHECK(cost=1)
);
"""

class CreditBudgetError(ValueError):
    """Sanitized denial; never include a filesystem path or provider secret."""


def _day(value: str) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise CreditBudgetError("Invalid UTC budget day")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise CreditBudgetError("Invalid UTC budget day") from None
    return value


def _hash(value: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise CreditBudgetError("Invalid evidence fingerprint")
    return value


def _check_private_storage(path: Path) -> None:
    """Fail closed on shared/misowned ledger storage before SQLite access.

    Only the immediate ledger directory and the ledger inode are checked.
    This is not a substitute for an isolated mount, backups or OS ACL review.
    """
    try:
        uid = os.getuid()
        parent = os.lstat(path.parent)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid
                or parent.st_mode & 0o077):
            raise CreditBudgetError("Durable ledger directory must be private")
        try:
            entry = os.lstat(path)
        except FileNotFoundError:
            return  # Provisioning may create the file, reservation may not.
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != uid
                or entry.st_nlink != 1 or entry.st_mode & 0o077):
            raise CreditBudgetError("Durable ledger file must be private")
    except (OSError, AttributeError):
        raise CreditBudgetError("Cannot verify private ledger storage") from None


def _path(db_path: str) -> Path:
    if not isinstance(db_path, str) or not 1 <= len(db_path) <= 1024:
        raise CreditBudgetError("Invalid durable ledger location")
    path = Path(db_path)
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise CreditBudgetError("Invalid durable ledger location")
    _check_private_storage(path)
    return path


def _connect(path: Path) -> sqlite3.Connection:
    # mode=rw refuses missing files; reservations never create an empty ledger.
    _check_private_storage(path)
    uri = "file:" + quote(str(path), safe="/") + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
    try:
        _check_private_storage(path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        return conn
    except BaseException:
        conn.close()
        raise


def provision_daily_budget(
    db_path: str, *, utc_day: str, max_credits: int,
    entitlement_evidence_sha256: str, rights_evidence_sha256: str,
    owner_confirmed: bool = False,
) -> None:
    """One-time operator provisioning; NEVER verifies provider rights itself.

    The caller must authenticate the operator and independently verify the
    entitlement and rights evidence. Existing daily policy cannot be changed.
    """
    if owner_confirmed is not True:
        raise CreditBudgetError("Explicit owner provisioning required")
    _day(utc_day)
    if type(max_credits) is not int or not 1 <= max_credits <= 5000:
        raise CreditBudgetError("Invalid daily credit cap")
    _hash(entitlement_evidence_sha256)
    _hash(rights_evidence_sha256)
    path = _path(db_path)
    try:
        # First-time creation is explicit and private. Never follow a symlink.
        if not path.exists():
            fd = os.open(
                path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            os.close(fd)
        _check_private_storage(path)
        with closing(_connect(path)) as conn:
            conn.executescript(_SCHEMA)  # schema only; never contains user input
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO daily_policy VALUES (?, 'twelvedata', 'XAU/USD', "
                "'completed-m1-review', ?, ?, ?)",
                (utc_day, max_credits, entitlement_evidence_sha256, rights_evidence_sha256),
            )
            conn.commit()
    except (OSError, sqlite3.Error):
        raise CreditBudgetError("Budget provisioning failed or policy already exists") from None


def reserve_one_credit(
    db_path: str, *, request_id: str, manifest_sha256: str,
) -> dict:
    """Atomically consume one credit before a potentially chargeable request.

    Repeated request IDs are denied, including after a crash or uncertain
    vendor outcome. No automatic refunds and no implicit policy rollover.
    """
    if not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None:
        raise CreditBudgetError("Invalid unique request identity")
    _hash(manifest_sha256)
    path = _path(db_path)
    if not path.is_file():
        raise CreditBudgetError("Durable budget not provisioned")
    try:
        with closing(_connect(path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Sample UTC only AFTER acquiring SQLite's write lock. Sampling
            # before a contended BEGIN could backdate a reservation by the
            # lock wait and permit a second call <60s after the real attempt.
            now = int(time.time())
            if not 60 <= now <= 253402300799:
                raise CreditBudgetError("Invalid server UTC clock")
            utc_day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            row = conn.execute(
                "SELECT max_credits, entitlement_evidence_sha256, "
                "rights_evidence_sha256 FROM daily_policy WHERE utc_day=? "
                "AND provider='twelvedata' AND symbol='XAU/USD' "
                "AND purpose='completed-m1-review'", (utc_day,),
            ).fetchone()
            if row is None:
                raise CreditBudgetError("No owner-provisioned budget for current UTC day")
            cap, entitlement, rights = row
            if (type(cap) is not int or not 1 <= cap <= 5000
                    or not isinstance(entitlement, str) or _HASH.fullmatch(entitlement) is None
                    or not isinstance(rights, str) or _HASH.fullmatch(rights) is None):
                raise CreditBudgetError("Corrupt budget policy")
            used_row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(cost), 0) FROM credit_reservation "
                "WHERE utc_day=?", (utc_day,),
            ).fetchone()
            count, used = used_row
            if used != count or used < 0 or used >= cap:
                raise CreditBudgetError("Daily provider credit budget exhausted or invalid")
            # Calendar-minute buckets permit two calls one second apart at
            # xx:xx:59 and xx:xx+1:00. Enforce a rolling 60-second separation
            # instead, across UTC midnight and daily policy boundaries. A
            # future reservation also blocks calls after a clock rollback.
            # This check and INSERT share one IMMEDIATE transaction, so
            # concurrent workers cannot bypass the ceiling.
            recent_count = conn.execute(
                "SELECT COUNT(*) FROM credit_reservation "
                "WHERE reserved_at_utc>?",
                (now - 60,),
            ).fetchone()[0]
            if type(recent_count) is not int or recent_count != 0:
                raise CreditBudgetError("Per-minute provider request safety limit reached")
            conn.execute(
                "INSERT INTO credit_reservation VALUES (?, ?, ?, ?, 1)",
                (request_id, utc_day, manifest_sha256, now),
            )
            conn.commit()
            return {
                "reservation_id": request_id,
                "utc_day": utc_day,
                "remaining_credits": cap - used - 1,
                "entitlement_verified": False,
                "rights_verified": False,
            }
    except CreditBudgetError:
        raise
    except (OSError, sqlite3.Error):
        raise CreditBudgetError("Credit reservation failed or request already reserved") from None
