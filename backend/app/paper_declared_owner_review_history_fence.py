"""Offline append-only declared owner-review history diagnostic; NEVER authorizes orders.

All evidence, including history and clocks, is supplied by an untrusted caller.
A digest is an integrity comparison aid, not an authenticated audit anchor.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_MAX_MS = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT = frozenset({"broker", "account_alias", "session_id", "sequence", "observed_at_ms", "events"})
_EVENT = frozenset({"approval_id", "client_order_id", "order_intent_sha", "preview_digest",
                    "decision", "issued_at_ms", "expires_at_ms", "recorded_at_ms"})


def _ms(value: Any, field: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"Invalid {field}")
    return value


def _id(value: Any, field: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {field}")
    return value


def _digest(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value) or value == "0" * 64:
        raise ValueError(f"Invalid {field}")
    return value


def _parse(snapshot: Any, now: int, label: str) -> tuple[dict, set[str]]:
    if type(snapshot) is not dict or set(snapshot) != _SNAPSHOT:
        raise ValueError(f"Invalid {label} snapshot fields")
    for field in ("broker", "account_alias", "session_id"):
        _id(snapshot[field], field)
    seq = snapshot["sequence"]
    if type(seq) is not int or not 0 <= seq <= 2**63 - 1:
        raise ValueError("Invalid sequence")
    observed = _ms(snapshot["observed_at_ms"], "snapshot observation")
    events = snapshot["events"]
    if type(events) is not list or len(events) > 512:
        raise ValueError("Invalid owner-review history population")
    failures: set[str] = set()
    if observed > now or (label == "current" and now - observed > 30_000):
        failures.add(f"{label}_snapshot_stale_or_future")
    approval_ids: set[str] = set()
    approved_orders: set[str] = set()
    approved_intents: set[str] = set()
    rejected_intents: set[str] = set()
    rejected_orders: set[str] = set()
    order_intents: dict[str, str] = {}
    intent_orders: dict[str, str] = {}
    preview_orders: dict[str, tuple[str, str]] = {}
    last_recorded = -1
    for event in events:
        if type(event) is not dict or set(event) != _EVENT:
            raise ValueError("Invalid owner-review event fields")
        aid = _id(event["approval_id"], "approval ID")
        cid = _id(event["client_order_id"], "client order ID")
        intent = _digest(event["order_intent_sha"], "order intent digest")
        preview = _digest(event["preview_digest"], "preview digest")
        # A client order, intent and complete review preview must not silently
        # acquire a different identity in later declared history entries.
        if cid in order_intents and order_intents[cid] != intent:
            failures.add("client_order_rebound_to_different_intent")
        if intent in intent_orders and intent_orders[intent] != cid:
            failures.add("order_intent_rebound_to_different_client_order")
        if preview in preview_orders and preview_orders[preview] != (cid, intent):
            failures.add("preview_digest_reused_for_distinct_order")
        order_intents.setdefault(cid, intent)
        intent_orders.setdefault(intent, cid)
        preview_orders.setdefault(preview, (cid, intent))
        decision = event["decision"]
        if type(decision) is not str or decision not in ("APPROVE", "REJECT"):
            raise ValueError("Invalid review decision")
        issued = _ms(event["issued_at_ms"], "issued time")
        expires = _ms(event["expires_at_ms"], "expiry time")
        recorded = _ms(event["recorded_at_ms"], "recorded time")
        if aid in approval_ids:
            failures.add("duplicate_approval_id")
        approval_ids.add(aid)
        if recorded <= last_recorded:
            failures.add("non_monotonic_review_recording")
        last_recorded = recorded
        if not issued <= recorded <= observed <= now:
            failures.add("invalid_review_event_chronology")
        if not issued < expires <= issued + 30_000:
            failures.add("invalid_review_lifetime")
        if decision == "APPROVE":
            if recorded >= expires:
                failures.add("approval_recorded_after_expiry")
            if cid in approved_orders or intent in approved_intents:
                failures.add("duplicate_approved_order_or_intent")
            if intent in rejected_intents:
                failures.add("approval_after_rejection_same_intent")
            if cid in rejected_orders:
                failures.add("approval_after_rejection_same_client_order")
            approved_orders.add(cid)
            approved_intents.add(intent)
        else:
            if cid in approved_orders or intent in approved_intents:
                failures.add("rejection_after_approval_same_order_or_intent")
            if cid in rejected_orders or intent in rejected_intents:
                failures.add("duplicate_rejected_order_or_intent")
            rejected_orders.add(cid)
            rejected_intents.add(intent)
    return snapshot, failures


def inspect_declared_owner_review_history_fence(
    previous: dict | None, current: dict, now_ms: int,
) -> dict[str, Any]:
    """Detect self-contradictory or rewritten caller-declared review histories.

    This function does not validate signatures, authenticate history, consume
    approval IDs, reserve funds, or submit orders. An independent durable
    trusted audit anchor is required before any production reliance.
    """
    now = _ms(now_ms, "evaluation time")
    curr, failures = _parse(current, now, "current")
    appended = 0
    if previous is None:
        failures.add("missing_independent_prior_history")
    else:
        prev, prior_failures = _parse(previous, now, "previous")
        failures.update(prior_failures)
        if (curr["broker"], curr["account_alias"]) != (prev["broker"], prev["account_alias"]):
            failures.add("broker_account_changed")
        if curr["session_id"] != prev["session_id"]:
            failures.add("session_change_requires_external_reconciliation")
        if curr["observed_at_ms"] < prev["observed_at_ms"]:
            failures.add("snapshot_time_rollback")
        old, new = prev["events"], curr["events"]
        if len(new) < len(old) or new[:len(old)] != old:
            failures.add("history_rewritten_or_truncated")
        appended = max(0, len(new) - len(old))
        if appended:
            if curr["sequence"] != prev["sequence"] + 1:
                failures.add("history_revision_not_advanced_once")
            if old and new[len(old)]["recorded_at_ms"] <= old[-1]["recorded_at_ms"]:
                failures.add("appended_review_time_not_advanced")
        elif curr["sequence"] != prev["sequence"]:
            failures.add("revision_changed_without_append")
        if curr["sequence"] < prev["sequence"]:
            failures.add("history_revision_rollback")
    fingerprint = hashlib.sha256(json.dumps(curr, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
    return {
        "status": "HOLD_DECLARED_REVIEW_HISTORY" if failures else "DECLARED_REVIEW_HISTORY_UNVERIFIED",
        "failed_checks": sorted(failures),
        "current_history_digest": fingerprint,
        "appended_events": appended,
        "history_authenticated": False,
        "independent_audit_anchor_verified": False,
        "owner_identity_authenticated": False,
        "approval_signature_verified": False,
        "approval_nonce_atomically_consumed": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
