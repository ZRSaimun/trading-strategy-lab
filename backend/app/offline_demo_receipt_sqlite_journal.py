"""Offline SQLite CAS journal for *declared* demo-order receipt snapshots.

Never connects to a broker or authorizes orders. Local SQLite transactions and
SHA-256 detect some accidental inconsistency, NOT forged broker evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from urllib.parse import quote

from app.offline_demo_order_receipt_replay import replay_declared_demo_order_receipts
from app.offline_demo_receipt_snapshot_continuity import (
    audit_declared_demo_receipt_snapshot_continuity,
)

_PROTOCOL = "offline-demo-receipt-sqlite-journal-v1"
_ZERO = "0" * 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY = ("provider", "venue", "account_alias", "instrument", "client_order_id")
_MAX_SNAPSHOTS = 128
_MAX_PAYLOAD_BYTES = 1_000_000


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _key(scope):
    return _digest({field: scope[field] for field in _IDENTITY})


def _checkpoint(key, revision, previous, payload):
    return _digest({"protocol": _PROTOCOL, "order_key": key,
                    "revision": revision, "previous_checkpoint_sha256": previous,
                    "snapshot": payload})


def _path(db_path):
    if not isinstance(db_path, (str, os.PathLike)):
        raise ValueError("A local filesystem journal path is required")
    path = os.fspath(db_path)
    if (not isinstance(path, str) or not path or path == ":memory:"
            or "\x00" in path):
        raise ValueError("A durable local filesystem journal path is required")
    return os.path.abspath(path)


def _open(db_path, *, writable):
    path = _path(db_path)
    if writable:
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("""CREATE TABLE IF NOT EXISTS demo_order_journal (
            order_key TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            head_sha256 TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS demo_order_snapshots (
            order_key TEXT NOT NULL, revision INTEGER NOT NULL,
            previous_sha256 TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (order_key, revision),
            FOREIGN KEY (order_key) REFERENCES demo_order_journal(order_key))""")
    else:
        if not os.path.isfile(path):
            raise ValueError("No existing local journal")
        uri = "file:" + quote(path, safe="/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    return conn


def _load(conn, key):
    """Revalidate every stored snapshot and chained checkpoint, not just head."""
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("SQLite journal integrity check failed")
    header = conn.execute(
        "SELECT revision, head_sha256 FROM demo_order_journal WHERE order_key=?",
        (key,)).fetchone()
    if header is None:
        return []
    count = conn.execute(
        "SELECT count(*) FROM demo_order_snapshots WHERE order_key=?",
        (key,)).fetchone()[0]
    if not (1 <= count <= _MAX_SNAPSHOTS):
        raise ValueError("Missing or unbounded stored snapshot population")
    rows = conn.execute(
        """SELECT revision, previous_sha256, checkpoint_sha256, payload_json
           FROM demo_order_snapshots WHERE order_key=? ORDER BY revision""",
        (key,)).fetchall()
    previous = _ZERO
    snapshots = []
    for expected_revision, (revision, previous_sha, checkpoint_sha, raw) in enumerate(rows, 1):
        if (type(revision) is not int or revision != expected_revision
                or previous_sha != previous or type(raw) is not str
                or len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES):
            raise ValueError("Broken journal revision, chain or size bound")
        try:
            payload = json.loads(raw)
            if (_canonical(payload) != raw or type(payload) is not dict
                    or set(payload) != {"scope", "events", "manifest"}):
                raise ValueError("Noncanonical stored snapshot")
            if _key(payload["scope"]) != key:
                raise ValueError("Changed stored order identity")
            replay_declared_demo_order_receipts(
                payload["scope"], payload["events"], payload["manifest"])
            if snapshots:
                prior = snapshots[-1]["payload"]
                audit_declared_demo_receipt_snapshot_continuity(
                    prior["scope"], prior["events"], prior["manifest"],
                    payload["scope"], payload["events"], payload["manifest"])
            if checkpoint_sha != _checkpoint(key, revision, previous, payload):
                raise ValueError("Stored checkpoint digest mismatch")
        except (KeyError, TypeError, json.JSONDecodeError, OverflowError) as exc:
            raise ValueError("Invalid stored snapshot") from exc
        snapshots.append({"revision": revision, "checkpoint_sha256": checkpoint_sha,
                          "previous_checkpoint_sha256": previous, "payload": payload})
        previous = checkpoint_sha
    if header != (len(snapshots), previous):
        raise ValueError("Journal head disagrees with stored snapshot chain")
    return snapshots


def _report(snapshot, *, status):
    payload = snapshot["payload"]
    replay = replay_declared_demo_order_receipts(
        payload["scope"], payload["events"], payload["manifest"])
    return {
        "status": status,
        "revision": snapshot["revision"],
        "checkpoint_sha256": snapshot["checkpoint_sha256"],
        "previous_checkpoint_sha256": snapshot["previous_checkpoint_sha256"],
        "as_of_ms": payload["scope"]["as_of_ms"],
        "declared_filled_contracts": replay["declared_filled_contracts"],
        "declared_remaining_contracts": replay["declared_remaining_contracts"],
        "local_chain_consistent": True,
        "broker_receipts_authenticated": False,
        "broker_population_complete": False,
        "manual_broker_reconciliation_required": True,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
    }


def append_declared_demo_receipt_snapshot(
    db_path, scope, events, manifest, expected_previous_checkpoint_sha256,
):
    """Atomically append a fully revalidated snapshot using compare-and-swap.

    The caller must retain the previous checkpoint separately. A byte-identical
    retry with the same prior checkpoint is idempotent; stale competing writers
    fail closed. A successful commit does not prove actual broker exposure.
    """
    if (type(expected_previous_checkpoint_sha256) is not str
            or not _SHA.fullmatch(expected_previous_checkpoint_sha256)):
        raise ValueError("Invalid expected checkpoint SHA-256")
    replay_declared_demo_order_receipts(scope, events, manifest)
    payload = {"scope": scope, "events": events, "manifest": manifest}
    raw = _canonical(payload)
    if len(raw.encode("ascii")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("Unbounded declared receipt snapshot")
    key = _key(scope)
    conn = _open(db_path, writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = _load(conn, key)
        if prior:
            latest = prior[-1]
            if (raw == _canonical(latest["payload"]) and
                    expected_previous_checkpoint_sha256 ==
                    latest["previous_checkpoint_sha256"]):
                conn.execute("COMMIT")
                return _report(latest, status="IDEMPOTENT_DECLARED_RETRY")
            if expected_previous_checkpoint_sha256 != latest["checkpoint_sha256"]:
                raise ValueError("Stale or conflicting journal compare-and-swap")
            before = latest["payload"]
            audit_declared_demo_receipt_snapshot_continuity(
                before["scope"], before["events"], before["manifest"],
                scope, events, manifest)
        elif expected_previous_checkpoint_sha256 != _ZERO:
            raise ValueError("New order requires genesis checkpoint")
        if len(prior) >= _MAX_SNAPSHOTS:
            raise ValueError("Journal snapshot limit reached")
        revision = len(prior) + 1
        checkpoint = _checkpoint(
            key, revision, expected_previous_checkpoint_sha256, payload)
        if not prior:
            conn.execute(
                "INSERT INTO demo_order_journal VALUES (?, ?, ?)", (key, 0, _ZERO))
        conn.execute(
            "INSERT INTO demo_order_snapshots VALUES (?, ?, ?, ?, ?)",
            (key, revision, expected_previous_checkpoint_sha256, checkpoint, raw))
        updated = conn.execute(
            """UPDATE demo_order_journal SET revision=?, head_sha256=?
               WHERE order_key=? AND revision=? AND head_sha256=?""",
            (revision, checkpoint, key, revision - 1,
             expected_previous_checkpoint_sha256))
        if updated.rowcount != 1:
            raise ValueError("Concurrent journal head changed")
        conn.execute("COMMIT")
        return _report(
            {"revision": revision, "checkpoint_sha256": checkpoint,
             "previous_checkpoint_sha256": expected_previous_checkpoint_sha256,
             "payload": payload},
            status="DECLARED_SNAPSHOT_LOCALLY_COMMITTED")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def read_declared_demo_receipt_journal_head(db_path, scope):
    """Read and revalidate a stored head without modifying the SQLite file."""
    key = _key(scope)
    conn = _open(db_path, writable=False)
    try:
        snapshots = _load(conn, key)
        if not snapshots:
            raise ValueError("No matching declared demo order")
        return _report(snapshots[-1], status="LOCAL_JOURNAL_ONLY_NOT_BROKER_VERIFIED")
    finally:
        conn.close()
