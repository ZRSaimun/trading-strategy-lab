"""Offline, local-only overlap lock for declared holdout populations.

A SQLite registry is not immutable or independently timestamped. This adds
cross-study row overlap defense for cooperating callers, not source proof.
No network, broker access, order routes, or outcome reads.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing

from app.local_holdout_release_registry import (
    _SCHEMA, _clock, _connect, _path,
)

_ROW_SCHEMA = """CREATE TABLE IF NOT EXISTS holdout_locked_rows (
    source_sha256 TEXT NOT NULL,
    row_sha256 TEXT NOT NULL,
    study_id TEXT NOT NULL,
    PRIMARY KEY (source_sha256, row_sha256)
)"""

_DECISION_SCHEMA = """CREATE TABLE IF NOT EXISTS holdout_locked_decisions (
    source_sha256 TEXT NOT NULL,
    decision_at_utc INTEGER NOT NULL,
    study_id TEXT NOT NULL,
    PRIMARY KEY (source_sha256, decision_at_utc)
)"""


_PAIR_SCHEMA = """CREATE TABLE IF NOT EXISTS holdout_locked_pairs (
    source_sha256 TEXT NOT NULL,
    row_sha256 TEXT NOT NULL,
    decision_at_utc INTEGER NOT NULL,
    study_id TEXT NOT NULL,
    PRIMARY KEY (source_sha256, row_sha256),
    UNIQUE (source_sha256, decision_at_utc)
)"""


def _source_key(source):
    """Bind rows to a declared market feed across accounts and archive splits."""
    feed = {key: source[key] for key in (
        "provider", "venue", "instrument", "quote_side", "utc_convention",
    )}
    return hashlib.sha256(json.dumps(
        feed, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()


def register_population_locked_holdout(db_path, manifest, census):
    """Register a declared study and atomically reserve every declared source row.

    Duplicate or partially overlapping populations on the same declared feed
    are rejected, even across different study IDs, candidates, or census order.
    This also locks declared feed decision timestamps, so changed row bytes
    cannot silently recycle the same timestamp within this local registry.
    It cannot detect falsified feed identities, other database files, or
    access to outcomes outside the cooperating API.
    """
    from app.declared_holdout_release_gate import (
        _validate_census, prepare_declared_holdout_manifest_sha256,
    )

    digest = prepare_declared_holdout_manifest_sha256(manifest)
    _validate_census(manifest, census)
    now = _clock()
    # A declared registration timestamp in the local clock's future is not
    # point-in-time evidence. Reject it before creating or changing the DB.
    if now < manifest["registered_at_utc"]:
        raise ValueError("Local registration precedes declared registration timestamp")
    if now >= manifest["holdout_start_at_utc"]:
        raise ValueError("Registration must precede holdout start")
    path = _path(db_path)
    source_key = _source_key(manifest["source"])
    study_id = manifest["study_id"]

    with closing(_connect(path, create=True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # CREATE TABLE IF NOT EXISTS also accepts a same-named SQLite
            # view. INSTEAD OF INSERT triggers on such views can silently
            # absorb reservations and return a false registration success.
            # Reject all reserved-name shadowing before creating any tables.
            reserved_objects = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE name IN "
                "('holdout_claims', 'holdout_locked_rows', "
                "'holdout_locked_decisions', 'holdout_locked_pairs')"
            ).fetchall()
            if any(kind != "table" for _, kind in reserved_objects):
                raise ValueError("Invalid population-lock schema object at registration")
            # Real tables can also have AFTER INSERT triggers that silently
            # delete or rewrite reservations while INSERT reports success.
            # Reject triggers attached to any protected table before writes.
            # BEGIN IMMEDIATE keeps this schema preflight and inserts atomic.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name IN "
                "('holdout_claims', 'holdout_locked_rows', "
                "'holdout_locked_decisions', 'holdout_locked_pairs') LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Invalid population-lock trigger at registration")
            conn.execute(_SCHEMA)
            # Existing row-only registries cannot be upgraded safely without
            # their original committed censuses. Never infer or backfill them.
            has_decisions = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='holdout_locked_decisions'"
            ).fetchone() is not None
            if not has_decisions and conn.execute(
                "SELECT 1 FROM holdout_claims LIMIT 1"
            ).fetchone() is not None:
                has_rows = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='holdout_locked_rows'"
                ).fetchone() is not None
                if has_rows and conn.execute(
                    "SELECT 1 FROM holdout_locked_rows LIMIT 1"
                ).fetchone() is not None:
                    raise ValueError("Existing row-locked registry lacks decision-time reservations")
                raise ValueError("Legacy unreserved holdout claims block population locking")
            # A row/time registry without original pair commitments cannot
            # be upgraded by guessing pairings from two independent sets.
            has_pairs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='holdout_locked_pairs'"
            ).fetchone() is not None
            if has_decisions and not has_pairs and conn.execute(
                "SELECT 1 FROM holdout_claims LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Existing population-locked registry lacks paired reservations")
            conn.execute(_ROW_SCHEMA)
            conn.execute(_DECISION_SCHEMA)
            conn.execute(_PAIR_SCHEMA)
            # Fail closed if any earlier study has missing row or timestamp
            # reservations, or mismatched counts across both populations.
            if conn.execute(
                "SELECT 1 FROM holdout_claims AS c WHERE "
                "(SELECT count(*) FROM holdout_locked_rows AS r WHERE r.study_id=c.study_id) = 0 "
                "OR (SELECT count(*) FROM holdout_locked_rows AS r WHERE r.study_id=c.study_id) "
                "!= (SELECT count(*) FROM holdout_locked_decisions AS d "
                "WHERE d.study_id=c.study_id) LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Incomplete row or decision-time holdout reservations")
            # Refuse to add a new study to a registry with orphaned or
            # balanced-but-inconsistent reservations from an older study.
            if (conn.execute(
                "SELECT 1 FROM holdout_locked_rows AS r LEFT JOIN "
                "holdout_claims AS c ON c.study_id=r.study_id "
                "WHERE c.study_id IS NULL LIMIT 1"
            ).fetchone() is not None or conn.execute(
                "SELECT 1 FROM holdout_locked_decisions AS d LEFT JOIN "
                "holdout_claims AS c ON c.study_id=d.study_id "
                "WHERE c.study_id IS NULL LIMIT 1"
            ).fetchone() is not None):
                raise ValueError("Orphaned population reservations block registration")
            if conn.execute(
                "SELECT 1 FROM holdout_locked_decisions AS d JOIN "
                "holdout_claims AS c ON c.study_id=d.study_id WHERE "
                "typeof(d.decision_at_utc) != 'integer' OR "
                "d.decision_at_utc < c.holdout_start_at_utc OR "
                "d.decision_at_utc >= c.holdout_end_at_utc LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Noncausal population decision reservations block registration")
            if conn.execute(
                "SELECT 1 FROM (SELECT study_id, source_sha256 FROM "
                "holdout_locked_rows UNION ALL SELECT study_id, source_sha256 "
                "FROM holdout_locked_decisions) AS p GROUP BY study_id "
                "HAVING count(DISTINCT source_sha256) != 1 LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Split-source population reservations block registration")
            # Verify all three reservation views agree before adding a study.
            # A balanced replacement or missing pair must never be accepted.
            if conn.execute(
                "SELECT 1 FROM holdout_claims AS c WHERE "
                "(SELECT count(*) FROM holdout_locked_pairs AS p WHERE p.study_id=c.study_id) "
                "!= (SELECT count(*) FROM holdout_locked_rows AS r WHERE r.study_id=c.study_id) "
                "LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Incomplete paired population reservations")
            if conn.execute(
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
                raise ValueError("Inconsistent paired population reservations")
            conn.execute(
                "INSERT INTO holdout_claims VALUES (?, ?, ?, ?, ?, NULL)",
                (study_id, digest, manifest["holdout_start_at_utc"],
                 manifest["holdout_end_at_utc"], now),
            )
            # The UNIQUE pair rejects any shared row on the same declared
            # source. An integrity error rolls back both tables atomically.
            conn.executemany(
                "INSERT INTO holdout_locked_rows "
                "(source_sha256, row_sha256, study_id) VALUES (?, ?, ?)",
                ((source_key, row["row_sha256"], study_id) for row in census),
            )
            # A revised vendor row hash cannot bypass the same-feed,
            # same-decision-time lock. Both tables commit or roll back together.
            conn.executemany(
                "INSERT INTO holdout_locked_decisions "
                "(source_sha256, decision_at_utc, study_id) VALUES (?, ?, ?)",
                ((source_key, row["decision_at_utc"], study_id) for row in census),
            )
            conn.executemany(
                "INSERT INTO holdout_locked_pairs "
                "(source_sha256, row_sha256, decision_at_utc, study_id) "
                "VALUES (?, ?, ?, ?)",
                ((source_key, row["row_sha256"], row["decision_at_utc"], study_id)
                 for row in census),
            )
            # Waiting for a SQLite writer or inserting a large census can
            # cross the holdout start. Recheck after reservations and fail
            # atomically rather than committing a late registration.
            committed_at = _clock()
            if (committed_at < now or
                    committed_at < manifest["registered_at_utc"] or
                    committed_at >= manifest["holdout_start_at_utc"]):
                raise ValueError("Registration clock moved backwards or reached holdout start")
            conn.execute(
                "UPDATE holdout_claims SET registered_at_utc=? WHERE study_id=?",
                (committed_at, study_id))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {
        "study_id": study_id,
        "manifest_sha256": digest,
        "registered_at_utc": committed_at,
        "declared_source_key_sha256": source_key,
        "locked_observation_count": len(census),
        "locked_decision_count": len(census),
        "locked_pair_count": len(census),
        "local_registry_only": True,
        "independently_trusted_registry": False,
    }
