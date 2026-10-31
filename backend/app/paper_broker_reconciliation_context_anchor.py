"""Fail-closed offline custody check for broker reconciliation *context*.

Snapshot-only hashes do not bind the expected UNKNOWN intent set, the caller's
checkpoint clocks, or the gap policy. This is an additive diagnostic, not a
broker authentication mechanism, quarantine release, or order execution gate.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.paper_broker_inventory_census import MAX_MS
from app.paper_broker_snapshot_anchor_audit import inspect_declared_snapshot_anchors
from app.paper_broker_snapshot_chain_audit import (
    MAX_CHAIN_SNAPSHOTS,
    MAX_CHECKPOINT_GAP_MS,
)

_CONTEXT_DOMAIN = b"trading-lab:declared-broker-reconciliation-context:v1\x00"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CONTEXT_BYTES = 262_144


def _prior_digest(value: Any) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value) or value == "0" * 64:
        raise ValueError("Invalid prior reconciliation context digest")
    return value


def fingerprint_declared_reconciliation_context(
    expected: dict,
    check_times_ms: list[int],
    max_checkpoint_gap_ms: int = MAX_CHECKPOINT_GAP_MS,
) -> str:
    """Hash the declared UNKNOWN intent population, clocks and exact gap policy.

    Callers MUST first validate the full evidence chain and independently
    retain this digest before the evidence can be modified. This helper is
    only a deterministic fingerprint, not a broker or clock validator.
    """
    if type(expected) is not dict:
        raise ValueError("Invalid declared reconciliation context")
    if type(check_times_ms) is not list or not 2 <= len(check_times_ms) <= MAX_CHAIN_SNAPSHOTS:
        raise ValueError("Invalid declared checkpoint population")
    if any(type(t) is not int or not 0 <= t <= MAX_MS for t in check_times_ms):
        raise ValueError("Invalid declared checkpoint time")
    if any(b <= a for a, b in zip(check_times_ms, check_times_ms[1:])):
        raise ValueError("Nonmonotonic declared checkpoint times")
    if type(max_checkpoint_gap_ms) is not int or not 1 <= max_checkpoint_gap_ms <= MAX_CHECKPOINT_GAP_MS:
        raise ValueError("Invalid declared gap policy")
    payload = {
        "schema": "declared-broker-reconciliation-context-v1",
        "expected": expected,
        "check_times_ms": check_times_ms,
        "max_checkpoint_gap_ms": max_checkpoint_gap_ms,
    }
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Context is not canonical JSON") from exc
    if len(encoded) > _MAX_CONTEXT_BYTES:
        raise ValueError("Declared reconciliation context too large")
    return hashlib.sha256(_CONTEXT_DOMAIN + len(encoded).to_bytes(8, "big") + encoded).hexdigest()


def inspect_declared_reconciliation_context_anchors(
    expected: dict,
    snapshots: list[dict],
    check_times_ms: list[int],
    prior_snapshot_digests: list[str],
    prior_chain_digest: str,
    prior_context_digest: str,
    max_checkpoint_gap_ms: int = MAX_CHECKPOINT_GAP_MS,
) -> dict[str, Any]:
    """Require matching snapshot AND context digests; NEVER authorize orders.

    Prior digests are caller-supplied. Even matching hashes cannot prove their
    custody or authenticate a provider's account, orders, fills or timestamps.
    """
    _prior_digest(prior_context_digest)
    audit = inspect_declared_snapshot_anchors(
        expected, snapshots, check_times_ms, prior_snapshot_digests,
        prior_chain_digest, max_checkpoint_gap_ms=max_checkpoint_gap_ms,
    )
    actual = fingerprint_declared_reconciliation_context(
        expected, check_times_ms, max_checkpoint_gap_ms)
    failures = set(audit["failed_checks"])
    if actual != prior_context_digest:
        failures.add("reconciliation_context_digest_mismatch")
    return {
        **audit,
        "status": ("HOLD_RECONCILIATION" if failures
                   else "DECLARED_CONTEXT_ANCHOR_CANDIDATE_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "context_custody_authenticated": False,
        "broker_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
