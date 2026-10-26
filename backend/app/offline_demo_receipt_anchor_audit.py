"""Read-only comparison of local demo receipt journals with declared off-journal anchors.

A matching caller-supplied anchor is NOT a signature, authenticated broker
receipt, independently stored witness, or authorization to execute orders.
"""
from __future__ import annotations

import re

from app.offline_demo_receipt_sqlite_journal import _key, _load, _open

_MAX_ANCHORS = 32
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_WITNESS = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9._:/#-]{1,160}\Z")
_FIELDS = frozenset({
    "revision", "checkpoint_sha256", "previous_checkpoint_sha256",
    "as_of_ms", "witnessed_at_ms", "witness_id", "evidence_ref",
})


def audit_declared_demo_receipt_anchor_evidence(
    db_path, scope, anchors, evaluation_as_of_ms,
):
    """Compare supplied off-journal claims against every referenced stored revision.

    `anchors` must be a bounded, ascending list of independently retained
    *claims*. This function cannot prove independent retention or witness
    identity; consumers must authenticate custody and broker population outside
    this offline library. A new journal head without a corresponding anchor
    remains on hold, not silently approved.
    """
    if type(evaluation_as_of_ms) is not int or evaluation_as_of_ms <= 0:
        raise ValueError("Invalid evaluation cutoff")
    if type(anchors) not in (list, tuple) or not 1 <= len(anchors) <= _MAX_ANCHORS:
        raise ValueError("Anchor population must be nonempty and bounded")
    if type(scope) is not dict:
        raise ValueError("Invalid declared order scope")
    key = _key(scope)
    conn = _open(db_path, writable=False)
    try:
        snapshots = _load(conn, key)
    finally:
        conn.close()
    if not snapshots:
        raise ValueError("No matching local declared order history")

    last_revision = 0
    last_witnessed_at = 0
    evidence_refs = set()
    for anchor in anchors:
        if type(anchor) is not dict or set(anchor) != _FIELDS:
            raise ValueError("Invalid declared anchor shape")
        revision = anchor["revision"]
        witnessed = anchor["witnessed_at_ms"]
        as_of = anchor["as_of_ms"]
        if (type(revision) is not int or revision <= last_revision
                or revision > len(snapshots)):
            raise ValueError("Missing, rolled-back or nonascending anchored revision")
        if (type(as_of) is not int or type(witnessed) is not int
                or as_of <= 0 or witnessed < as_of
                or witnessed < last_witnessed_at
                or witnessed > evaluation_as_of_ms):
            raise ValueError("Invalid anchor observation chronology")
        if (type(anchor["witness_id"]) is not str
                or not _WITNESS.fullmatch(anchor["witness_id"])):
            raise ValueError("Invalid declared witness identifier")
        ref = anchor["evidence_ref"]
        if (type(ref) is not str or not _REFERENCE.fullmatch(ref)
                or ref in evidence_refs):
            raise ValueError("Invalid or reused evidence reference")
        evidence_refs.add(ref)
        snapshot = snapshots[revision - 1]
        for field in ("checkpoint_sha256", "previous_checkpoint_sha256"):
            value = anchor[field]
            if (type(value) is not str or not _SHA.fullmatch(value)
                    or value != snapshot[field]):
                raise ValueError("Declared external anchor disagrees with local chain")
        if as_of != snapshot["payload"]["scope"]["as_of_ms"]:
            raise ValueError("Declared anchor cutoff disagrees with local snapshot")
        last_revision = revision
        last_witnessed_at = witnessed

    head = snapshots[-1]
    head_anchored = last_revision == head["revision"]
    return {
        "engine": "offline-demo-receipt-anchor-audit-v1",
        "status": ("DECLARED_HEAD_ANCHOR_MATCH_ONLY" if head_anchored
                   else "HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED"),
        "order_identity_sha256": key,
        "local_head_revision": head["revision"],
        "local_head_sha256": head["checkpoint_sha256"],
        "last_declared_anchored_revision": last_revision,
        "declared_anchor_count": len(anchors),
        "head_has_matching_declared_anchor": head_anchored,
        "external_witness_authenticated": False,
        "independent_custody_verified": False,
        "broker_receipts_authenticated": False,
        "broker_population_complete": False,
        "manual_broker_reconciliation_required": True,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
    }
