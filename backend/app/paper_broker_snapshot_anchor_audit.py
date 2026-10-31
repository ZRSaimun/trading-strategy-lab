"""Offline broker snapshot digest cross-check; never authorizes order execution.

Caller-provided SHA-256 anchors are NOT proof of broker origin, integrity, or
independent custody. Only anchors obtained earlier via a separate trusted
channel can reveal subsequent mutation. This module makes no network or disk
access, and never releases an UNKNOWN submission.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.paper_broker_snapshot_chain_audit import (
    MAX_CHAIN_SNAPSHOTS,
    MAX_CHECKPOINT_GAP_MS,
    inspect_declared_snapshot_chain,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT_DOMAIN = b"trading-lab:declared-broker-snapshot:v1\x00"
_CHAIN_DOMAIN = b"trading-lab:declared-broker-snapshot-chain:v1\x00"


def _digest(value: Any, name: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value) or value == "0" * 64:
        raise ValueError(f"Invalid {name}")
    return value


def fingerprint_declared_snapshot(snapshot: dict) -> str:
    """Deterministic digest of JSON snapshot fields, not broker authentication.

    The caller must first validate the snapshot against the census schema.
    This function is deliberately not an authorization or validation gate.
    """
    if type(snapshot) is not dict:
        raise ValueError("Invalid snapshot")
    try:
        payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Snapshot is not canonical JSON") from exc
    return hashlib.sha256(_SNAPSHOT_DOMAIN + len(payload).to_bytes(8, "big") + payload).hexdigest()


def fingerprint_declared_chain(snapshot_digests: list[str]) -> str:
    """Order-sensitive digest over 2..16 prevalidated snapshot fingerprints."""
    if type(snapshot_digests) is not list or not 2 <= len(snapshot_digests) <= MAX_CHAIN_SNAPSHOTS:
        raise ValueError("Invalid snapshot fingerprint population")
    validated = [_digest(value, "snapshot fingerprint") for value in snapshot_digests]
    payload = b"".join(bytes.fromhex(digest) for digest in validated)
    return hashlib.sha256(_CHAIN_DOMAIN + len(validated).to_bytes(2, "big") + payload).hexdigest()


def inspect_declared_snapshot_anchors(expected: dict, snapshots: list[dict],
                                      check_times_ms: list[int],
                                      prior_snapshot_digests: list[str],
                                      prior_chain_digest: str,
                                      max_checkpoint_gap_ms: int = MAX_CHECKPOINT_GAP_MS) -> dict[str, Any]:
    """Compare a fully audited chain to caller-declared preexisting anchors.

    Anchors must have been retained *before* the snapshots under investigation
    could be changed. Even a match cannot establish that custody was trusted.
    Schema errors raise ValueError and fail closed.
    """
    _digest(prior_chain_digest, "prior chain digest")
    if type(prior_snapshot_digests) is not list or not 2 <= len(prior_snapshot_digests) <= MAX_CHAIN_SNAPSHOTS:
        raise ValueError("Invalid prior snapshot digest population")
    for item in prior_snapshot_digests:
        _digest(item, "prior snapshot digest")
    # Validate the complete snapshot evidence and clock policy before hashing.
    audit = inspect_declared_snapshot_chain(expected, snapshots, check_times_ms,
                                            max_checkpoint_gap_ms=max_checkpoint_gap_ms)
    if len(prior_snapshot_digests) != len(snapshots):
        raise ValueError("Prior digest count does not match snapshot count")
    actual = [fingerprint_declared_snapshot(snapshot) for snapshot in snapshots]
    failures = set(audit["failed_checks"])
    if any(a != b for a, b in zip(actual, prior_snapshot_digests)):
        failures.add("snapshot_digest_mismatch")
    if fingerprint_declared_chain(actual) != prior_chain_digest:
        failures.add("chain_digest_mismatch")
    return {
        "status": ("HOLD_RECONCILIATION" if failures else
                   "DECLARED_ANCHOR_CANDIDATE_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "snapshot_count": len(snapshots),
        "broker_authenticated": False,
        "anchor_custody_authenticated": False,
        "snapshot_completeness_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
