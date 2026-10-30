"""Offline SQLite CAS journal for caller-declared completed M1 checkpoints.

This persists declared data, not authenticated market observations. No routes,
network, polling, provider calls, broker access or order permissions.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
import re
import sqlite3
from urllib.parse import quote

from .expected_bar_manifest import (
    ExpectedM1Manifest, audit_m1_receipts_against_manifest,
    compile_expected_m1_manifest,
)
from .prospective_receipt_continuity import audit_declared_m1_receipt_continuity

_PROTOCOL = "declared-m1-checkpoint-sqlite-v1"
_ZERO = "0" * 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SNAPSHOTS = 16
_MAX_PAYLOAD_BYTES = 4_000_000
_ID_FIELDS = ("provider", "symbol", "venue", "price_side",
              "calendar_id", "calendar_revision", "calendar_source")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _key(manifest):
    return _hash({name: getattr(manifest, name) for name in _ID_FIELDS})


def _checkpoint(key, revision, previous, payload):
    return _hash({"protocol": _PROTOCOL, "scope_key": key,
                  "revision": revision, "previous_sha256": previous,
                  "payload": payload})


def _path(db_path):
    if not isinstance(db_path, (str, os.PathLike)):
        raise ValueError("Durable local SQLite path required")
    path = os.fspath(db_path)
    if (not isinstance(path, str) or not path or path == ":memory:"
            or "\x00" in path):
        raise ValueError("Durable local SQLite path required")
    return os.path.abspath(path)


def _open(db_path, *, writable):
    path = _path(db_path)
    if writable:
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("""CREATE TABLE IF NOT EXISTS declared_m1_heads (
            scope_key TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            head_sha256 TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS declared_m1_snapshots (
            scope_key TEXT NOT NULL, revision INTEGER NOT NULL,
            previous_sha256 TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(scope_key, revision),
            FOREIGN KEY(scope_key) REFERENCES declared_m1_heads(scope_key))""")
    else:
        if not os.path.isfile(path):
            raise ValueError("No existing local journal")
        conn = sqlite3.connect(
            "file:" + quote(path, safe="/") + "?mode=ro",
            uri=True, timeout=5, isolation_level=None)
    return conn


def _manifest(data):
    if type(data) is not dict or set(data) != set(ExpectedM1Manifest.__dataclass_fields__):
        raise ValueError("Invalid stored manifest")
    rebuilt = compile_expected_m1_manifest(
        **{k: data[k] for k in _ID_FIELDS},
        observed_at_utc=data["observed_at_utc"],
        sessions_utc=data["sessions_utc"],
        exclusions_utc=data["exclusions_utc"],
    )
    if (tuple(rebuilt.expected_minutes) != tuple(data["expected_minutes"])
            or rebuilt.manifest_sha256 != data["manifest_sha256"]):
        raise ValueError("Stored manifest fingerprint or population changed")
    return rebuilt


def _validate(payload):
    if type(payload) is not dict or set(payload) != {"manifest", "receipts"}:
        raise ValueError("Invalid checkpoint payload")
    manifest = _manifest(payload["manifest"])
    report = audit_m1_receipts_against_manifest(payload["receipts"], manifest)
    if report["status"] != "INTERNAL_CENSUS_ONLY_NOT_LIVE":
        raise ValueError("Declared receipt census requires review")
    return manifest


def _load(conn, key):
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign-key check failed")
    header = conn.execute(
        "SELECT revision, head_sha256 FROM declared_m1_heads WHERE scope_key=?",
        (key,)).fetchone()
    count = conn.execute(
        "SELECT count(*) FROM declared_m1_snapshots WHERE scope_key=?",
        (key,)).fetchone()[0]
    if header is None:
        if count:
            raise ValueError("Orphaned receipt snapshots")
        return []
    if not 1 <= count <= _MAX_SNAPSHOTS:
        raise ValueError("Missing or unbounded checkpoint population")
    rows = conn.execute(
        """SELECT revision, previous_sha256, checkpoint_sha256, payload_json
           FROM declared_m1_snapshots WHERE scope_key=? ORDER BY revision""",
        (key,)).fetchall()
    previous = _ZERO
    snapshots = []
    for expected_revision, (revision, prev, digest, raw) in enumerate(rows, 1):
        if (type(revision) is not int or revision != expected_revision
                or prev != previous or type(raw) is not str
                or len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES):
            raise ValueError("Broken or oversized stored receipt chain")
        try:
            payload = json.loads(raw)
            if _canonical(payload) != raw:
                raise ValueError("Noncanonical stored receipt snapshot")
            manifest = _validate(payload)
            if _key(manifest) != key:
                raise ValueError("Stored receipt identity changed")
            if snapshots:
                prior = snapshots[-1]
                result = audit_declared_m1_receipt_continuity(
                    prior["payload"]["receipts"], payload["receipts"],
                    prior["manifest"], manifest)
                if result["status"] != "INTERNAL_CONTINUITY_ONLY_NOT_LIVE":
                    raise ValueError("Stored receipt history requires review")
            if digest != _checkpoint(key, revision, previous, payload):
                raise ValueError("Stored receipt checkpoint hash mismatch")
        except (KeyError, TypeError, OverflowError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid stored receipt checkpoint") from exc
        snapshots.append({"revision": revision, "previous_sha256": previous,
                          "checkpoint_sha256": digest, "payload": payload,
                          "manifest": manifest})
        previous = digest
    if header != (len(snapshots), previous):
        raise ValueError("Receipt journal head does not match history")
    return snapshots


def _report(snapshot, status):
    return {
        "protocol": _PROTOCOL, "status": status,
        "revision": snapshot["revision"],
        "checkpoint_sha256": snapshot["checkpoint_sha256"],
        "previous_checkpoint_sha256": snapshot["previous_sha256"],
        "declared_receipt_rows": len(snapshot["payload"]["receipts"]),
        "declared_observed_at_utc": snapshot["manifest"].observed_at_utc,
        "local_chain_consistent": True,
        "source_authenticated": False,
        "server_receipt_clock_attested": False,
        "provider_entitlement_verified": False,
        "expected_calendar_verified": False,
        "retention_and_display_rights_verified": False,
        "live": False, "may_execute_order": False,
    }


def append_declared_m1_checkpoint(
    db_path, receipts, manifest, expected_previous_checkpoint_sha256,
):
    """Atomic compare-and-swap append; no unsafe history or price revisions.

    The caller must retain an independently anchored checkpoint to detect
    whole-database rollback. This journal cannot attest caller timestamps.
    """
    if (type(expected_previous_checkpoint_sha256) is not str
            or not _SHA.fullmatch(expected_previous_checkpoint_sha256)):
        raise ValueError("Invalid expected checkpoint SHA-256")
    if type(manifest) is not ExpectedM1Manifest:
        raise ValueError("Compiled M1 manifest required")
    payload = {"manifest": asdict(manifest), "receipts": receipts}
    raw = _canonical(payload)
    if len(raw.encode("ascii")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("Unbounded declared receipt checkpoint")
    _validate(payload)
    key = _key(manifest)
    conn = _open(db_path, writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = _load(conn, key)
        if prior:
            latest = prior[-1]
            if (raw == _canonical(latest["payload"])
                    and expected_previous_checkpoint_sha256 == latest["previous_sha256"]):
                conn.execute("COMMIT")
                return _report(latest, "IDEMPOTENT_DECLARED_RETRY")
            if expected_previous_checkpoint_sha256 != latest["checkpoint_sha256"]:
                raise ValueError("Stale or conflicting checkpoint compare-and-swap")
            result = audit_declared_m1_receipt_continuity(
                latest["payload"]["receipts"], receipts,
                latest["manifest"], manifest)
            if result["status"] != "INTERNAL_CONTINUITY_ONLY_NOT_LIVE":
                raise ValueError("New checkpoint requires continuity review")
        elif expected_previous_checkpoint_sha256 != _ZERO:
            raise ValueError("Genesis requires zero checkpoint")
        if len(prior) >= _MAX_SNAPSHOTS:
            raise ValueError("Bounded receipt journal is full")
        revision = len(prior) + 1
        digest = _checkpoint(key, revision, expected_previous_checkpoint_sha256, payload)
        if not prior:
            conn.execute("INSERT INTO declared_m1_heads VALUES (?, ?, ?)",
                         (key, 0, _ZERO))
        conn.execute("INSERT INTO declared_m1_snapshots VALUES (?, ?, ?, ?, ?)",
                     (key, revision, expected_previous_checkpoint_sha256, digest, raw))
        updated = conn.execute(
            """UPDATE declared_m1_heads SET revision=?, head_sha256=?
               WHERE scope_key=? AND revision=? AND head_sha256=?""",
            (revision, digest, key, revision - 1, expected_previous_checkpoint_sha256))
        if updated.rowcount != 1:
            raise ValueError("Concurrent receipt head changed")
        conn.execute("COMMIT")
        return _report({"revision": revision, "previous_sha256":
                        expected_previous_checkpoint_sha256, "checkpoint_sha256": digest,
                        "payload": payload, "manifest": manifest},
                       "DECLARED_CHECKPOINT_LOCALLY_COMMITTED")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def read_declared_m1_checkpoint_head(db_path, manifest):
    """Read-only revalidation of all retained snapshots, no provider access."""
    if type(manifest) is not ExpectedM1Manifest:
        raise ValueError("Compiled M1 manifest required")
    conn = _open(db_path, writable=False)
    try:
        snapshots = _load(conn, _key(manifest))
        if not snapshots:
            raise ValueError("No matching declared M1 receipt journal")
        return _report(snapshots[-1], "LOCAL_DECLARED_CHAIN_ONLY_NOT_LIVE")
    finally:
        conn.close()
