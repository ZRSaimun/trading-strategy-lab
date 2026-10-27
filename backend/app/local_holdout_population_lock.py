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
    This cannot detect changed/fabricated row hashes, legacy registrations,
    other database files, or access to outcomes outside the cooperating API.
    """
    from app.declared_holdout_release_gate import (
        _validate_census, prepare_declared_holdout_manifest_sha256,
    )

    digest = prepare_declared_holdout_manifest_sha256(manifest)
    _validate_census(manifest, census)
    now = _clock()
    if now >= manifest["holdout_start_at_utc"]:
        raise ValueError("Registration must precede holdout start")
    path = _path(db_path)
    source_key = _source_key(manifest["source"])
    study_id = manifest["study_id"]

    with closing(_connect(path, create=True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_SCHEMA)
            conn.execute(_ROW_SCHEMA)
            # A legacy study registered before the first population lock has
            # no row reservations. Refuse to mix registration modes rather
            # than claim complete cross-study overlap protection.
            if conn.execute(
                "SELECT 1 FROM holdout_claims AS c WHERE NOT EXISTS "
                "(SELECT 1 FROM holdout_locked_rows AS r WHERE r.study_id=c.study_id) "
                "LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("Legacy unreserved holdout claims block population locking")
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
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {
        "study_id": study_id,
        "manifest_sha256": digest,
        "registered_at_utc": now,
        "declared_source_key_sha256": source_key,
        "locked_observation_count": len(census),
        "local_registry_only": True,
        "independently_trusted_registry": False,
    }
