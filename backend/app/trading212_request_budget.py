"""Opt-in durable reservations for Trading 212 read-only GET requests.

Not wired into the broker adapter or website. A reservation is irrevocably
consumed, including on failed HTTP calls. No keys, CFD or orders.
The operator must verify that every key for an account shares one private,
durable ledger; independent external API clients cannot be controlled.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import quote

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST = re.compile(r"[0-9a-f]{32}\Z")
_ENDPOINTS = frozenset({"instruments", "exchanges", "account_summary"})
_MIN_SPACING_SECONDS = 60
_MAX_DAILY_REQUESTS = 50
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  account_scope_sha256 TEXT NOT NULL,
  environment TEXT NOT NULL CHECK(environment IN ('DEMO','LIVE')),
  account_type TEXT NOT NULL CHECK(account_type IN ('INVEST','STOCKS_ISA'))
);
CREATE TABLE IF NOT EXISTS daily_policy (
  utc_day TEXT PRIMARY KEY,
  max_requests INTEGER NOT NULL CHECK(max_requests BETWEEN 1 AND 50),
  rights_evidence_sha256 TEXT NOT NULL,
  entitlement_evidence_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_reservation (
  request_id TEXT PRIMARY KEY,
  utc_day TEXT NOT NULL REFERENCES daily_policy(utc_day),
  endpoint TEXT NOT NULL CHECK(endpoint IN ('instruments','exchanges','account_summary')),
  reserved_at_utc INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_time ON request_reservation(reserved_at_utc);
"""


class BrokerBudgetError(ValueError):
    """Sanitized default-deny outcome, without paths, account IDs or keys."""


def _sha(value: object) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise BrokerBudgetError("Invalid evidence or account fingerprint")
    return value


def _storage(path_str: str) -> Path:
    if not isinstance(path_str, str) or not 1 <= len(path_str) <= 1024:
        raise BrokerBudgetError("Invalid durable ledger location")
    path = Path(path_str)
    if not path.is_absolute():
        raise BrokerBudgetError("Absolute durable ledger location required")
    try:
        parent = os.lstat(path.parent)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or parent.st_mode & 0o077):
            raise BrokerBudgetError("Private durable ledger directory required")
        try:
            entry = os.lstat(path)
        except FileNotFoundError:
            return path
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.getuid()
                or entry.st_nlink != 1 or entry.st_mode & 0o077):
            raise BrokerBudgetError("Private regular ledger file required")
    except (OSError, AttributeError):
        raise BrokerBudgetError("Cannot verify private ledger storage") from None
    return path


def _connect(path: Path) -> sqlite3.Connection:
    _storage(str(path))
    uri = "file:" + quote(str(path), safe="/") + "?mode=rw"
    try:
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10)
        try:
            _storage(str(path))
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA journal_mode=DELETE")
            return conn
        except BaseException:
            conn.close()
            raise
    except sqlite3.Error:
        raise BrokerBudgetError("Durable ledger unavailable") from None


def _clock() -> tuple[int, str]:
    now = int(time.time())
    if not 1577836800 <= now <= 253402300799:
        raise BrokerBudgetError("Untrusted local UTC clock")
    return now, datetime.fromtimestamp(now, timezone.utc).date().isoformat()


def provision_trading212_read_budget(
    db_path: str, *, account_scope_sha256: str, environment: str,
    account_type: str, utc_day: str, max_requests: int,
    rights_evidence_sha256: str, entitlement_evidence_sha256: str,
    owner_confirmed: bool = False,
) -> None:
    """Create immutable today-only owner-declared budget; never verify rights."""
    scope = _sha(account_scope_sha256)
    rights = _sha(rights_evidence_sha256)
    entitlement = _sha(entitlement_evidence_sha256)
    _, today = _clock()
    if (owner_confirmed is not True or environment not in ("DEMO", "LIVE")
            or account_type not in ("INVEST", "STOCKS_ISA")
            or not isinstance(utc_day, str) or utc_day != today
            or type(max_requests) is not int or not 1 <= max_requests <= _MAX_DAILY_REQUESTS):
        raise BrokerBudgetError("Explicit valid owner budget required for today")
    path = _storage(db_path)
    if not path.exists():
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        except OSError:
            raise BrokerBudgetError("Cannot provision private ledger") from None
    with closing(_connect(path)) as conn:
        try:
            conn.executescript(_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            identity = conn.execute("SELECT account_scope_sha256,environment,account_type FROM ledger_identity WHERE singleton=1").fetchone()
            declared = (scope, environment, account_type)
            if identity is None:
                conn.execute("INSERT INTO ledger_identity VALUES (1,?,?,?)", declared)
            elif tuple(identity) != declared:
                raise BrokerBudgetError("Ledger belongs to another declared account scope")
            existing = conn.execute("SELECT max_requests,rights_evidence_sha256,entitlement_evidence_sha256 FROM daily_policy WHERE utc_day=?", (utc_day,)).fetchone()
            policy = (max_requests, rights, entitlement)
            if existing is not None and tuple(existing) != policy:
                raise BrokerBudgetError("Existing daily budget cannot be changed")
            if existing is None:
                conn.execute("INSERT INTO daily_policy VALUES (?,?,?,?)", (utc_day, *policy))
            conn.commit()
        except (sqlite3.Error, BrokerBudgetError):
            conn.rollback()
            raise BrokerBudgetError("Budget provisioning denied") from None


def reserve_trading212_read(
    db_path: str, *, request_id: str, endpoint: str,
    account_scope_sha256: str, environment: str, account_type: str,
) -> dict:
    """Irrevocably reserve one request before an explicitly approved GET."""
    if (not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id)
            or not isinstance(endpoint, str) or endpoint not in _ENDPOINTS
            or environment not in ("DEMO", "LIVE")
            or account_type not in ("INVEST", "STOCKS_ISA")):
        raise BrokerBudgetError("Invalid read reservation request")
    scope = _sha(account_scope_sha256)
    now, today = _clock()
    path = _storage(db_path)
    if not path.exists():
        raise BrokerBudgetError("No provisioned durable ledger")
    with closing(_connect(path)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            identity = conn.execute("SELECT account_scope_sha256,environment,account_type FROM ledger_identity WHERE singleton=1").fetchone()
            if identity is None or tuple(identity) != (scope, environment, account_type):
                raise BrokerBudgetError("Unverified ledger account scope")
            policy = conn.execute("SELECT max_requests FROM daily_policy WHERE utc_day=?", (today,)).fetchone()
            if policy is None or type(policy[0]) is not int or not 1 <= policy[0] <= _MAX_DAILY_REQUESTS:
                raise BrokerBudgetError("No valid owner budget for today")
            previous = conn.execute("SELECT MAX(reserved_at_utc) FROM request_reservation").fetchone()[0]
            if previous is not None and (type(previous) is not int or now - previous < _MIN_SPACING_SECONDS):
                raise BrokerBudgetError("Conservative account-wide pacing denial")
            count = conn.execute("SELECT COUNT(*) FROM request_reservation WHERE utc_day=?", (today,)).fetchone()[0]
            if count >= policy[0]:
                raise BrokerBudgetError("Daily owner budget exhausted")
            conn.execute("INSERT INTO request_reservation VALUES (?,?,?,?)", (request_id, today, endpoint, now))
            conn.commit()
        except (sqlite3.Error, BrokerBudgetError):
            conn.rollback()
            raise BrokerBudgetError("Read reservation denied") from None
    return {"status": "RESERVED_NOT_SENT", "utc_day": today,
            "reserved_at_utc": now, "endpoint": endpoint,
            "market_data_feed": False, "account_quota_verified": False,
            "safe_to_make_another_request": False, "may_execute_order": False}


def fetch_budgeted_trading212_readonly(
    *, db_path: str, request_id: str, account_scope_sha256: str,
    endpoint: str, account_type: str, environment: str,
    api_key: str, api_secret: str, transport=None,
) -> dict:
    """One explicitly invoked, pre-reserved read; never retry or refund.

    This helper is not connected to a route, scheduler or startup hook.
    """
    reserve_trading212_read(
        db_path, request_id=request_id, endpoint=endpoint,
        account_scope_sha256=account_scope_sha256,
        environment=environment, account_type=account_type,
    )
    from app.trading212_readonly import fetch_trading212_readonly
    return fetch_trading212_readonly(
        endpoint=endpoint, account_type=account_type, environment=environment,
        api_key=api_key, api_secret=api_secret, transport=transport,
    )
