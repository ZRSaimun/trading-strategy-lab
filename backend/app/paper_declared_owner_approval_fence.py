"""Offline human-review preview fence. Never authenticates approval or executes orders.

An APPROVE string or matching digest is caller-declared, not a signed owner action.
Every output explicitly denies paper/live execution and authenticated consent.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.paper_declared_order_risk_preview import inspect_declared_order_risk_preview

_MAX_MS = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\\Z")
_SHA = re.compile(r"[0-9a-f]{64}\\Z")
_APPROVAL_FIELDS = frozenset({
    "approval_id", "approver_alias", "decision", "preview_digest", "order_intent_sha",
    "client_order_id", "broker", "account_alias", "quote_source", "quote_observed_at_ms",
    "issued_at_ms", "expires_at_ms",
})


def _ms(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"Invalid {label}")
    return value


def _id(value: Any, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _sha(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def inspect_declared_owner_approval_fence(
    order: dict, quote: dict, account: dict, risk_policy: dict,
    recent_orders: list[dict], approval: dict | None,
    used_approval_ids: list[str], now_ms: int,
) -> dict[str, Any]:
    """Bind declared review to a complete risk-preview input; never authorize.

    This is NOT a signature validator, consent record, idempotency store, or
    execution gate. An actual live adapter must require independently verified
    single-use, per-order signed consent and atomic broker-state rechecks.
    """
    now = _ms(now_ms, "evaluation time")
    risk = inspect_declared_order_risk_preview(
        order, quote, account, risk_policy, recent_orders, now,
    )
    if type(used_approval_ids) is not list or len(used_approval_ids) > 10_000:
        raise ValueError("Invalid consumed approval IDs")
    seen: set[str] = set()
    for value in used_approval_ids:
        ident = _id(value, "consumed approval ID")
        if ident in seen:
            raise ValueError("Duplicate consumed approval ID")
        seen.add(ident)
    # Canonical hash binds quote, account, risk policy, order history and risk
    # outcome. It is an untrusted display fingerprint, not an HMAC/signature.
    payload = {
        "schema": "declared-owner-review-v1", "order": order, "quote": quote,
        "account": account, "risk_policy": risk_policy,
        "recent_orders": recent_orders, "risk_preview": risk,
    }
    fingerprint = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    failures: set[str] = set()
    if risk["failed_checks"]:
        failures.add("underlying_order_risk_hold")
    if approval is None:
        failures.add("missing_declared_owner_review")
    else:
        if type(approval) is not dict or set(approval) != _APPROVAL_FIELDS:
            raise ValueError("Invalid owner review schema")
        for field in ("approval_id", "approver_alias", "client_order_id", "broker",
                      "account_alias", "quote_source"):
            _id(approval[field], field)
        _sha(approval["preview_digest"], "review fingerprint")
        _sha(approval["order_intent_sha"], "review intent")
        for field in ("quote_observed_at_ms", "issued_at_ms", "expires_at_ms"):
            _ms(approval[field], field)
        if type(approval["decision"]) is not str or approval["decision"] not in ("APPROVE", "REJECT"):
            raise ValueError("Invalid review decision")
        if approval["decision"] != "APPROVE":
            failures.add("owner_review_not_positive")
        if approval["approval_id"] in seen:
            failures.add("owner_review_id_reused")
        if approval["preview_digest"] != fingerprint:
            failures.add("owner_review_preview_changed")
        for field, expected in (
            ("order_intent_sha", order["intent_sha"]),
            ("client_order_id", order["client_order_id"]),
            ("broker", account["broker"]),
            ("account_alias", account["account_alias"]),
            ("quote_source", quote["source"]),
            ("quote_observed_at_ms", quote["observed_at_ms"]),
        ):
            if type(approval[field]) is not type(expected) or approval[field] != expected:
                failures.add("owner_review_" + field + "_mismatch")
        issued, expires = approval["issued_at_ms"], approval["expires_at_ms"]
        if (issued < quote["received_at_ms"] or issued > now or
                expires <= issued or expires - issued > 30_000 or now >= expires):
            failures.add("owner_review_stale_or_invalid_clock")
    return {
        "status": "HOLD_DECLARED_OWNER_REVIEW" if failures else "DECLARED_OWNER_REVIEW_UNVERIFIED",
        "failed_checks": sorted(failures),
        "preview_digest": fingerprint,
        "risk_failed_checks": risk["failed_checks"],
        "owner_identity_authenticated": False,
        "approval_signature_verified": False,
        "approval_nonce_atomically_consumed": False,
        "broker_authenticated": False,
        "requires_individual_owner_approval": True,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
