"""Local SQLite one-attempt holdout release fence (offline, no brokerage access).

Defense in depth only: the local host, wall clock and SQLite file are not
independently trusted. Callers with raw outcome access can bypass this module.
"""
from __future__ import annotations

import re
from contextlib import closing
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TIME = 8_640_000_000
_SCHEMA = """CREATE TABLE IF NOT EXISTS holdout_claims (
    study_id TEXT PRIMARY KEY NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    holdout_start_at_utc INTEGER NOT NULL,
    holdout_end_at_utc INTEGER NOT NULL,
    registered_at_utc INTEGER NOT NULL,
    release_claimed_at_utc INTEGER,
    CHECK (holdout_start_at_utc < holdout_end_at_utc),
    CHECK (registered_at_utc < holdout_start_at_utc),
    CHECK (release_claimed_at_utc IS NULL OR
           release_claimed_at_utc >= holdout_end_at_utc)
)"""


def _now_utc_seconds():
    return int(time.time())


def _clock():
    now = _now_utc_seconds()
    if type(now) is not int or not 0 <= now <= _MAX_TIME:
        raise ValueError("Invalid local clock")
    return now


def _inputs(study_id, manifest_sha256):
    if type(study_id) is not str or _ID.fullmatch(study_id) is None:
        raise ValueError("Invalid study identity")
    if type(manifest_sha256) is not str or _SHA.fullmatch(manifest_sha256) is None:
        raise ValueError("Invalid manifest digest")


def _path(db_path):
    if not isinstance(db_path, (str, Path)):
        raise ValueError("Invalid registry path")
    path = Path(db_path).expanduser().resolve()
    if not path.is_absolute() or path == Path('/'):
        raise ValueError("Invalid registry path")
    return path


def _connect(path, *, create):
    if create:
        conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    else:
        # mode=rw rejects a missing registry rather than silently creating it.
        uri = "file:" + quote(str(path), safe="/") + "?mode=rw"
        conn = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn
    except BaseException:
        conn.close()
        raise


def register_local_holdout(db_path, *, study_id, manifest_sha256,
                           holdout_start_at_utc, holdout_end_at_utc):
    """Register one study before its holdout starts; never overwrite it.

    The digest and timestamps are declared. Only the local registration clock
    comes from the host; it is not independent timestamp attestation.
    """
    _inputs(study_id, manifest_sha256)
    if (type(holdout_start_at_utc) is not int or
            type(holdout_end_at_utc) is not int or
            not 0 <= holdout_start_at_utc < holdout_end_at_utc <= _MAX_TIME):
        raise ValueError("Invalid holdout interval")
    now = _clock()
    if now >= holdout_start_at_utc:
        raise ValueError("Registration must precede holdout start")
    path = _path(db_path)
    with closing(_connect(path, create=True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_SCHEMA)
            # Do not allow the legacy, row-unreserved path to bypass a
            # population-locked registry in this same SQLite database.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='holdout_locked_rows'"
            ).fetchone() is not None:
                raise ValueError("Population-locked registry rejects legacy registration")
            conn.execute("INSERT INTO holdout_claims VALUES (?, ?, ?, ?, ?, NULL)",
                         (study_id, manifest_sha256, holdout_start_at_utc,
                          holdout_end_at_utc, now))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {"study_id": study_id, "manifest_sha256": manifest_sha256,
            "registered_at_utc": now, "local_registry_only": True}


def claim_local_holdout_release(db_path, *, study_id, manifest_sha256,
                                expected_holdout_start_at_utc=None,
                                expected_holdout_end_at_utc=None):
    """Atomically consume the single local release attempt BEFORE reading outcomes.

    A crash or failed subsequent evaluation intentionally burns the attempt.
    A caller cannot change the registered holdout end or reset this claim via
    the API. File tampering/restoration remains outside the threat model.
    """
    _inputs(study_id, manifest_sha256)
    # The optional expected interval is supplied by the frozen manifest in
    # the guarded wrapper. Check both fields in the same transaction as the
    # one-attempt claim to avoid a preflight/claim race.
    if ((expected_holdout_start_at_utc is None) !=
            (expected_holdout_end_at_utc is None)):
        raise ValueError("Expected holdout interval must include both endpoints")
    if expected_holdout_start_at_utc is not None and (
            type(expected_holdout_start_at_utc) is not int or
            type(expected_holdout_end_at_utc) is not int or
            not 0 <= expected_holdout_start_at_utc <
            expected_holdout_end_at_utc <= _MAX_TIME):
        raise ValueError("Invalid expected holdout interval")
    now = _clock()
    path = _path(db_path)
    with closing(_connect(path, create=False)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT manifest_sha256, holdout_start_at_utc, "
                "holdout_end_at_utc, registered_at_utc, "
                "release_claimed_at_utc FROM holdout_claims WHERE study_id=?",
                (study_id,)).fetchone()
            if row is None or row[0] != manifest_sha256:
                raise ValueError("Study not registered with this manifest")
            if (expected_holdout_start_at_utc is not None and
                    (row[1] != expected_holdout_start_at_utc or
                     row[2] != expected_holdout_end_at_utc)):
                raise ValueError("Registered holdout interval differs from frozen manifest")
            # A population-locked registry must remain internally complete
            # at release time, not just when the study was registered. A
            # missing table, missing reservation, or orphaned reservation is
            # evidence of incomplete/tampered local state: never release.
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND "
                "name IN ('holdout_locked_rows', 'holdout_locked_decisions')"
            )}
            if tables:
                if tables != {'holdout_locked_rows', 'holdout_locked_decisions'}:
                    raise ValueError("Incomplete population-lock tables at release")
                if conn.execute(
                    "SELECT 1 FROM holdout_claims AS c WHERE "
                    "(SELECT count(*) FROM holdout_locked_rows AS r "
                    "WHERE r.study_id=c.study_id) = 0 OR "
                    "(SELECT count(*) FROM holdout_locked_rows AS r "
                    "WHERE r.study_id=c.study_id) != "
                    "(SELECT count(*) FROM holdout_locked_decisions AS d "
                    "WHERE d.study_id=c.study_id) LIMIT 1"
                ).fetchone() is not None:
                    raise ValueError("Incomplete population reservations at release")
                if (conn.execute(
                    "SELECT 1 FROM holdout_locked_rows AS r LEFT JOIN "
                    "holdout_claims AS c ON c.study_id=r.study_id "
                    "WHERE c.study_id IS NULL LIMIT 1"
                ).fetchone() is not None or conn.execute(
                    "SELECT 1 FROM holdout_locked_decisions AS d LEFT JOIN "
                    "holdout_claims AS c ON c.study_id=d.study_id "
                    "WHERE c.study_id IS NULL LIMIT 1"
                ).fetchone() is not None):
                    raise ValueError("Orphaned population reservations at release")
            # Equal row/decision counts are not sufficient: corrupted yet
            # balanced reservations may carry noncausal times or split the
            # declared feed across the two reservation tables.
            if tables and conn.execute(
                "SELECT 1 FROM holdout_locked_decisions AS d JOIN "
                "holdout_claims AS c ON c.study_id=d.study_id WHERE "
                "typeof(d.decision_at_utc) != 'integer' OR "
                "d.decision_at_utc < c.holdout_start_at_utc OR "
                "d.decision_at_utc >= c.holdout_end_at_utc LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Noncausal population decision reservation at release")
            if tables and conn.execute(
                "SELECT 1 FROM (SELECT study_id, source_sha256 FROM "
                "holdout_locked_rows UNION ALL SELECT study_id, source_sha256 "
                "FROM holdout_locked_decisions) AS p GROUP BY study_id "
                "HAVING count(DISTINCT source_sha256) != 1 LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Split-source population reservations at release")
            if now < row[2] or now < row[3]:
                raise ValueError("Holdout not complete or local clock moved backwards")
            if row[4] is not None:
                raise ValueError("Holdout release already claimed")
            changed = conn.execute(
                "UPDATE holdout_claims SET release_claimed_at_utc=? "
                "WHERE study_id=? AND release_claimed_at_utc IS NULL",
                (now, study_id)).rowcount
            if changed != 1:
                raise ValueError("Concurrent holdout claim")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {"study_id": study_id, "manifest_sha256": manifest_sha256,
            "release_claimed_at_utc": now, "local_one_attempt_claim_recorded": True,
            "independently_trusted_registry": False}


def audit_declared_holdout_release_once(db_path, manifest, census, anchor, outcome_loader):
    """Claim before any outcome evaluation; failed evaluation still burns claim.

    Never use this wrapper to imply that the local database is immutable,
    that source/receipt digests are authenticated, or that raw data is private.
    """
    if not callable(outcome_loader):
        raise ValueError("Outcome loader must be callable")
    from app.declared_holdout_release_gate import (
        audit_declared_holdout_release, prepare_declared_holdout_manifest_sha256)
    digest = prepare_declared_holdout_manifest_sha256(manifest)
    claim = claim_local_holdout_release(
        db_path, study_id=manifest["study_id"], manifest_sha256=digest,
        expected_holdout_start_at_utc=manifest["holdout_start_at_utc"],
        expected_holdout_end_at_utc=manifest["holdout_end_at_utc"])
    outcomes = outcome_loader()  # Only cooperating callers defer access until after claim.
    result = audit_declared_holdout_release(
        manifest, census, anchor, outcomes, claim["release_claimed_at_utc"])
    return {"declared_audit": result, "local_release_claim": claim}
