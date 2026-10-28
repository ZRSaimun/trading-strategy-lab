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


def _assert_claims_schema(conn):
    """Reject a same-named table with weakened identity/chronology constraints.

    SQLite's CREATE TABLE IF NOT EXISTS does not check an existing table's
    definition. These registries are created by this module; a different
    definition is not safe to use as a one-attempt release fence.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='holdout_claims'"
    ).fetchone()
    if row is None or row[0] != _SCHEMA.replace(" IF NOT EXISTS", "", 1):
        raise ValueError("Invalid holdout claims table definition")


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
            # SQLite resolves object names case-insensitively, while the
            # sqlite_master.name comparison below is case-sensitive. A
            # differently cased view must not shadow the claims table.
            claims_objects = conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE lower(name)='holdout_claims'"
            ).fetchall()
            if any(name != "holdout_claims" or kind != "table"
                   for name, kind in claims_objects):
                raise ValueError("Invalid holdout claims schema object at registration")
            # Legacy claim inserts can also be erased by a trigger, even
            # when the protected table itself has the expected name.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                "AND lower(tbl_name)='holdout_claims' LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Invalid holdout claims trigger at registration")
            conn.execute(_SCHEMA)
            _assert_claims_schema(conn)
            # Do not allow the legacy, row-unreserved path to bypass a
            # population-locked registry in this same SQLite database.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE lower(name) IN ('holdout_locked_rows', "
                "'holdout_locked_decisions', 'holdout_locked_pairs') LIMIT 1"
            ).fetchone() is not None:
                # Any partial reservation schema is evidence that this DB
                # cannot safely accept a new unreserved legacy study.
                raise ValueError("Population-locked registry rejects legacy registration")
            conn.execute("INSERT INTO holdout_claims VALUES (?, ?, ?, ?, ?, NULL)",
                         (study_id, manifest_sha256, holdout_start_at_utc,
                          holdout_end_at_utc, now))
            # BEGIN IMMEDIATE may wait on another writer. A pre-lock clock
            # sample cannot prove that registration finished before the
            # holdout opened. Recheck after all writes, before committing.
            committed_at = _clock()
            if committed_at < now or committed_at >= holdout_start_at_utc:
                raise ValueError("Registration clock moved backwards or reached holdout start")
            conn.execute(
                "UPDATE holdout_claims SET registered_at_utc=? WHERE study_id=?",
                (committed_at, study_id))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {"study_id": study_id, "manifest_sha256": manifest_sha256,
            "registered_at_utc": committed_at, "local_registry_only": True}


def claim_local_holdout_release(db_path, *, study_id, manifest_sha256,
                                expected_holdout_start_at_utc=None,
                                expected_holdout_end_at_utc=None,
                                expected_population_rows=None,
                                expected_source_key_sha256=None):
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
    # Optional exact frozen-census comparison. Direct legacy callers may omit
    # it; the guarded wrapper supplies it for a nonempty declared census.
    if (expected_population_rows is None) != (expected_source_key_sha256 is None):
        raise ValueError("Frozen population and source key must be supplied together")
    if expected_population_rows is not None:
        if (type(expected_source_key_sha256) is not str or
                _SHA.fullmatch(expected_source_key_sha256) is None or
                type(expected_population_rows) is not list or
                not 1 <= len(expected_population_rows) <= 10000):
            raise ValueError("Invalid frozen population commitment")
        seen_rows, seen_times = set(), set()
        for pair in expected_population_rows:
            if (type(pair) is not tuple or len(pair) != 2 or
                    type(pair[0]) is not str or _SHA.fullmatch(pair[0]) is None or
                    type(pair[1]) is not int or not 0 <= pair[1] <= _MAX_TIME or
                    pair[0] in seen_rows or pair[1] in seen_times):
                raise ValueError("Invalid frozen population row")
            seen_rows.add(pair[0])
            seen_times.add(pair[1])
    now = _clock()
    path = _path(db_path)
    with closing(_connect(path, create=False)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # SQLite object identifiers are case-insensitive, but
            # sqlite_master.name comparisons are not. Reject mixed-case
            # shadow objects before reading claims or treating a damaged
            # reservation view as an unreserved legacy registry.
            protected_objects = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE lower(name) IN "
                "('holdout_claims', 'holdout_locked_rows', "
                "'holdout_locked_decisions', 'holdout_locked_pairs')"
            ).fetchall()
            canonical_names = {'holdout_claims', 'holdout_locked_rows',
                               'holdout_locked_decisions', 'holdout_locked_pairs'}
            if any(kind != "table" or name not in canonical_names
                   for name, kind in protected_objects):
                raise ValueError("Invalid population-lock schema object at release")
            # An AFTER UPDATE trigger can silently clear a recorded release
            # claim while SQLite reports one row updated. Reject any trigger
            # attached to protected holdout tables before consuming the
            # one-attempt release, including triggers added after registration.
            # BEGIN IMMEDIATE keeps this check and the claim in one transaction.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND lower(tbl_name) IN "
                "('holdout_claims', 'holdout_locked_rows', "
                "'holdout_locked_decisions', 'holdout_locked_pairs') LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Invalid holdout registry trigger at release")
            _assert_claims_schema(conn)
            # Import lazily: the population lock imports this registry.
            from app.local_holdout_population_lock import _assert_reservation_schema
            if any(name != 'holdout_claims' for name, kind in protected_objects):
                _assert_reservation_schema(conn)
            row = conn.execute(
                "SELECT manifest_sha256, holdout_start_at_utc, "
                "holdout_end_at_utc, registered_at_utc, "
                "release_claimed_at_utc FROM holdout_claims WHERE study_id=?",
                (study_id,)).fetchone()
            if row is None or row[0] != manifest_sha256:
                raise ValueError("Study not registered with this manifest")
            # SQLite's INTEGER affinity and CHECK constraints alone do not
            # guarantee an integral, nonnegative persisted registration time.
            # A local edit to -1 or 100.5 can satisfy registered < start.
            # Reject corrupted chronology before burning the one attempt.
            start, end, registered = row[1:4]
            if (any(type(value) is not int for value in (start, end, registered))
                    or not 0 <= registered < start < end <= _MAX_TIME):
                raise ValueError("Invalid stored holdout chronology")
            if (expected_holdout_start_at_utc is not None and
                    (row[1] != expected_holdout_start_at_utc or
                     row[2] != expected_holdout_end_at_utc)):
                raise ValueError("Registered holdout interval differs from frozen manifest")
            # A population-locked registry must remain internally complete
            # at release time, not just when the study was registered. A
            # missing table, missing reservation, or orphaned reservation is
            # evidence of incomplete/tampered local state: never release.
            # A view or other named SQLite object masquerading as a
            # reservation table must never turn a damaged population lock
            # into an apparently unreserved legacy registry.
            population_objects = dict(conn.execute(
                "SELECT name, type FROM sqlite_master WHERE "
                "name IN ('holdout_locked_rows', 'holdout_locked_decisions', "
                "'holdout_locked_pairs')"
            ))
            if any(kind != "table" for kind in population_objects.values()):
                raise ValueError("Invalid population-lock schema object at release")
            tables = set(population_objects)
            # A caller that supplies a frozen census is requesting exact
            # population verification. A legacy registry without reservation
            # tables cannot satisfy that request: do not silently release.
            if expected_population_rows is not None and not tables:
                raise ValueError("Frozen population requires locked reservation tables")
            if tables:
                if tables != {'holdout_locked_rows', 'holdout_locked_decisions',
                              'holdout_locked_pairs'}:
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
            if tables and conn.execute(
                "SELECT 1 FROM holdout_claims AS c WHERE "
                "(SELECT count(*) FROM holdout_locked_pairs AS p "
                "WHERE p.study_id=c.study_id) != "
                "(SELECT count(*) FROM holdout_locked_rows AS r "
                "WHERE r.study_id=c.study_id) LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Incomplete paired population reservations at release")
            if tables and conn.execute(
                "SELECT 1 FROM holdout_locked_pairs AS p "
                "LEFT JOIN holdout_claims AS c ON c.study_id=p.study_id "
                "LEFT JOIN holdout_locked_rows AS r ON r.study_id=p.study_id "
                "AND r.source_sha256=p.source_sha256 AND r.row_sha256=p.row_sha256 "
                "LEFT JOIN holdout_locked_decisions AS d ON d.study_id=p.study_id "
                "AND d.source_sha256=p.source_sha256 "
                "AND d.decision_at_utc=p.decision_at_utc "
                "WHERE c.study_id IS NULL OR r.row_sha256 IS NULL "
                "OR d.decision_at_utc IS NULL LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Inconsistent paired population reservations at release")
            # Compare the *actual* row and decision sets with the caller's
            # frozen census under the same transaction as the release claim.
            # Counts and one-source checks alone miss balanced substitutions.
            population_matched = False
            if tables and expected_population_rows is not None:
                expected_rows = {(expected_source_key_sha256, r[0])
                                 for r in expected_population_rows}
                expected_decisions = {(expected_source_key_sha256, r[1])
                                      for r in expected_population_rows}
                actual_rows = set(conn.execute(
                    "SELECT source_sha256, row_sha256 FROM holdout_locked_rows "
                    "WHERE study_id=?", (study_id,)))
                actual_decisions = set(conn.execute(
                    "SELECT source_sha256, decision_at_utc FROM holdout_locked_decisions "
                    "WHERE study_id=?", (study_id,)))
                expected_pairs = {(expected_source_key_sha256, r[0], r[1])
                                  for r in expected_population_rows}
                actual_pairs = set(conn.execute(
                    "SELECT source_sha256, row_sha256, decision_at_utc "
                    "FROM holdout_locked_pairs WHERE study_id=?", (study_id,)))
                if (actual_rows != expected_rows or
                        actual_decisions != expected_decisions or
                        actual_pairs != expected_pairs):
                    raise ValueError("Frozen holdout population reservations differ")
                population_matched = True
            # A direct legacy claim without the frozen census must not burn
            # a population-locked study while bypassing its exact pairing
            # verification. Unreserved legacy registries remain compatible.
            if tables and not population_matched:
                raise ValueError(
                    "Population-locked release requires exact frozen census verification"
                )
            # The first clock sample precedes the SQLite writer lock. A
            # delayed claim must not use that stale sample if the local clock
            # has moved backwards while waiting for the transaction.
            claimed_at = _clock()
            if claimed_at < now or claimed_at < row[2] or claimed_at < row[3]:
                raise ValueError("Holdout not complete or local clock moved backwards")
            if row[4] is not None:
                raise ValueError("Holdout release already claimed")
            changed = conn.execute(
                "UPDATE holdout_claims SET release_claimed_at_utc=? "
                "WHERE study_id=? AND release_claimed_at_utc IS NULL",
                (claimed_at, study_id)).rowcount
            if changed != 1:
                raise ValueError("Concurrent holdout claim")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {"study_id": study_id, "manifest_sha256": manifest_sha256,
            "release_claimed_at_utc": claimed_at, "local_one_attempt_claim_recorded": True,
            "independently_trusted_registry": False,
            "local_frozen_population_matched": population_matched}


def audit_declared_holdout_release_once(db_path, manifest, census, anchor, outcome_loader):
    """Claim before any outcome evaluation; failed evaluation still burns claim.

    Never use this wrapper to imply that the local database is immutable,
    that source/receipt digests are authenticated, or that raw data is private.
    """
    if not callable(outcome_loader):
        raise ValueError("Outcome loader must be callable")
    from app.declared_holdout_release_gate import (
        _validate_anchor, _validate_census, audit_declared_holdout_release,
        prepare_declared_holdout_manifest_sha256)
    digest = prepare_declared_holdout_manifest_sha256(manifest)
    # Validate the frozen population BEFORE consuming a claim or calling an
    # outcome loader. A legacy registry without reservations must not allow
    # malformed or reselected census membership to reach raw outcomes first.
    _validate_census(manifest, census)
    # Reject invalid or late declared anchors before burning the only
    # release attempt or exposing raw outcomes to the caller's loader.
    # This is consistency validation, NOT external anchor authentication.
    _validate_anchor(manifest, anchor, digest)
    expected_rows = expected_source_key = None
    if type(census) is list and census:
        from app.local_holdout_population_lock import _source_key
        expected_rows = [(r["row_sha256"], r["decision_at_utc"]) for r in census]
        expected_source_key = _source_key(manifest["source"])
    claim = claim_local_holdout_release(
        db_path, study_id=manifest["study_id"], manifest_sha256=digest,
        expected_holdout_start_at_utc=manifest["holdout_start_at_utc"],
        expected_holdout_end_at_utc=manifest["holdout_end_at_utc"],
        expected_population_rows=expected_rows,
        expected_source_key_sha256=expected_source_key)
    outcomes = outcome_loader()  # Only cooperating callers defer access until after claim.
    result = audit_declared_holdout_release(
        manifest, census, anchor, outcomes, claim["release_claimed_at_utc"])
    return {"declared_audit": result, "local_release_claim": claim}
