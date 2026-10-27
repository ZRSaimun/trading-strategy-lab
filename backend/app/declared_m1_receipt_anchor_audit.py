"""Read-only audit of caller-supplied off-journal anchors for declared M1 receipts.

This checks local consistency with claimed anchors, not external custody,
authenticated vendor prices, independent timestamps or trading permissions.
"""
from __future__ import annotations

import re

from .expected_bar_manifest import ExpectedM1Manifest
from .declared_m1_receipt_sqlite_journal import _key, _load, _open

_PROTOCOL = "declared-m1-receipt-anchor-audit-v1"
_MAX_ANCHORS = 16
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_WITNESS = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9._:/#-]{1,160}\Z")
_FIELDS = frozenset({
    "scope_key", "revision", "checkpoint_sha256",
    "previous_checkpoint_sha256", "declared_observed_at_utc",
    "witnessed_at_utc", "witness_id", "evidence_ref",
})


def audit_declared_m1_receipt_anchor_evidence(
    db_path, manifest, anchors, evaluation_as_of_utc,
):
    """Compare independently retained *claims* with the revalidated local chain.

    The caller must obtain anchors from a separately controlled immutable
    witness and verify its custody/signature outside this module. The caller
    cannot use the journal itself as the witness. Unanchored newer heads HOLD.
    """
    if type(manifest) is not ExpectedM1Manifest:
        raise ValueError("Compiled M1 manifest required")
    if type(evaluation_as_of_utc) is not int or evaluation_as_of_utc <= 0:
        raise ValueError("Invalid evaluation cutoff")
    if type(anchors) not in (list, tuple) or not 1 <= len(anchors) <= _MAX_ANCHORS:
        raise ValueError("Anchor population must be nonempty and bounded")

    key = _key(manifest)
    conn = _open(db_path, writable=False)
    try:
        snapshots = _load(conn, key)
    finally:
        conn.close()
    if not snapshots:
        raise ValueError("No matching declared M1 receipt journal")
    if snapshots[-1]["manifest"].observed_at_utc > evaluation_as_of_utc:
        raise ValueError("Journal head unavailable at evaluation cutoff")

    last_revision = 0
    last_witnessed = 0
    last_observed = 0
    evidence_refs = set()
    for anchor in anchors:
        if type(anchor) is not dict or set(anchor) != _FIELDS:
            raise ValueError("Invalid declared M1 anchor shape")
        revision = anchor["revision"]
        observed = anchor["declared_observed_at_utc"]
        witnessed = anchor["witnessed_at_utc"]
        if (type(revision) is not int or revision <= last_revision
                or revision > len(snapshots)):
            raise ValueError("Missing, rolled-back or nonascending anchored revision")
        if (type(observed) is not int or type(witnessed) is not int
                or observed <= 0 or observed < last_observed
                or witnessed < observed or witnessed < last_witnessed
                or witnessed > evaluation_as_of_utc):
            raise ValueError("Invalid declared anchor chronology")
        if (type(anchor["witness_id"]) is not str
                or not _WITNESS.fullmatch(anchor["witness_id"])):
            raise ValueError("Invalid declared witness identifier")
        ref = anchor["evidence_ref"]
        if (type(ref) is not str or not _REFERENCE.fullmatch(ref)
                or ref in evidence_refs):
            raise ValueError("Invalid or reused anchor evidence reference")
        evidence_refs.add(ref)
        if anchor["scope_key"] != key:
            raise ValueError("Declared anchor source identity mismatch")
        snapshot = snapshots[revision - 1]
        if observed != snapshot["manifest"].observed_at_utc:
            raise ValueError("Declared anchor observation differs from journal")
        for claim_field, stored_field in (
            ("checkpoint_sha256", "checkpoint_sha256"),
            ("previous_checkpoint_sha256", "previous_sha256"),
        ):
            value = anchor[claim_field]
            if (type(value) is not str or not _SHA.fullmatch(value)
                    or value != snapshot[stored_field]):
                raise ValueError("Declared anchor disagrees with local receipt chain")
        last_revision = revision
        last_witnessed = witnessed
        last_observed = observed

    head = snapshots[-1]
    head_anchored = last_revision == head["revision"]
    return {
        "protocol": _PROTOCOL,
        "status": ("DECLARED_HEAD_ANCHOR_MATCH_ONLY" if head_anchored
                   else "HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED"),
        "scope_key": key,
        "local_head_revision": head["revision"],
        "local_head_sha256": head["checkpoint_sha256"],
        "last_declared_anchored_revision": last_revision,
        "declared_anchor_count": len(anchors),
        "head_has_matching_declared_anchor": head_anchored,
        "external_witness_authenticated": False,
        "independent_custody_verified": False,
        "provider_authenticated": False,
        "provider_entitlement_verified": False,
        "source_timestamp_authenticated": False,
        "market_calendar_verified": False,
        "live": False,
        "may_execute_order": False,
    }
