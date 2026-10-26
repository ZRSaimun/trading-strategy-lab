"""Fail-closed, read-only continuity check for two declared demo receipt snapshots.

Neither a durable journal nor authenticated broker evidence. Never sends orders.
"""
from __future__ import annotations

import hashlib
import json

from app.offline_demo_order_receipt_replay import replay_declared_demo_order_receipts

_SCOPE_IMMUTABLE = (
    "provider", "venue", "account_alias", "instrument", "client_order_id",
    "side", "requested_contracts", "submitted_at_ms", "intent_sha256",
)


def _unique(events):
    """Upstream replay has already validated sequences and exact duplicates."""
    seen = set()
    result = []
    for event in events:
        if event["sequence"] not in seen:
            seen.add(event["sequence"])
            result.append(event)
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def audit_declared_demo_receipt_snapshot_continuity(
    previous_scope, previous_events, previous_manifest,
    current_scope, current_events, current_manifest,
):
    """Revalidate both complete snapshots; reject history rewrites and late backfills.

    A later snapshot must retain every previously observed unique event exactly,
    with new receipts first received strictly after the earlier as-of cutoff.
    This is a consistency check over caller claims, NOT crash-safe storage or
    independent broker-event completeness proof.
    """
    previous = replay_declared_demo_order_receipts(
        previous_scope, previous_events, previous_manifest)
    current = replay_declared_demo_order_receipts(
        current_scope, current_events, current_manifest)

    if any(previous_scope[key] != current_scope[key] for key in _SCOPE_IMMUTABLE):
        raise ValueError("Changed immutable order, account or source identity")
    if current_scope["as_of_ms"] <= previous_scope["as_of_ms"]:
        raise ValueError("Current snapshot cutoff must strictly advance")
    if (current_manifest["manifest_recorded_at_ms"] <
            previous_manifest["manifest_recorded_at_ms"]):
        raise ValueError("Current manifest cannot predate previous manifest")

    before = _unique(previous_events)
    after = _unique(current_events)
    if len(after) < len(before):
        raise ValueError("Current snapshot omitted previously declared receipts")
    if after[:len(before)] != before:
        raise ValueError("Previously declared receipt prefix changed or was reordered")
    new = after[len(before):]
    if any(event["received_at_ms"] <= previous_scope["as_of_ms"] for event in new):
        raise ValueError("Late-discovered pre-cutoff receipt requires external reconciliation")

    # A self-declared digest is useful for comparison with an independently
    # retained checkpoint, but cannot authenticate the broker or source.
    previous_checkpoint = _digest({
        "scope": previous_scope, "manifest": previous_manifest,
        "unique_events": before,
    })
    current_checkpoint = _digest({
        "scope": current_scope, "manifest": current_manifest,
        "unique_events": after,
    })
    return {
        "engine": "offline-demo-receipt-snapshot-continuity-v1",
        "status": "DECLARED_CONTINUITY_ONLY",
        "previous_checkpoint_sha256": previous_checkpoint,
        "current_checkpoint_sha256": current_checkpoint,
        "previous_head_sha256": previous["head_sha256"],
        "current_head_sha256": current["head_sha256"],
        "previous_unique_receipts": len(before),
        "current_unique_receipts": len(after),
        "new_declared_receipts": len(new),
        "previous_declared_filled_contracts": previous["declared_filled_contracts"],
        "current_declared_filled_contracts": current["declared_filled_contracts"],
        "current_declared_remaining_contracts": current["declared_remaining_contracts"],
        "manual_broker_reconciliation_required": True,
        "broker_receipts_authenticated": False,
        "external_population_completeness_verified": False,
        "durable_transactional_storage_provided": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": (
            "Both snapshots and digests are caller-declared. Append-only consistency "
            "does not prove broker completeness, authentic fills, persistence, "
            "zero exposure, execution quality or profitability."
        ),
    }
