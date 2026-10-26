"""Offline, fail-closed replay of caller-declared demo order receipts.

NOT a broker adapter or durable store. Hashes are self-declared integrity receipts,
not signatures or evidence of complete broker events. Never authorizes an order.
"""
from __future__ import annotations

import hashlib
import json
import re

_PROTOCOL = "offline-demo-order-receipt-replay-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\\Z")
_SHA = re.compile(r"[0-9a-f]{64}\\Z")
_ZERO = "0" * 64
_MAX_MS = 100_000_000_000_000
_MAX_EVENTS = 2_000
_SCOPE = {"provider", "venue", "account_alias", "instrument", "client_order_id",
          "side", "requested_contracts", "submitted_at_ms", "as_of_ms", "intent_sha256"}
_EVENT = {"sequence", "event_id", "kind", "occurred_at_ms", "received_at_ms",
          "provider", "venue", "account_alias", "instrument", "client_order_id",
          "broker_order_id", "contracts", "receipt_sha256", "previous_event_sha256"}
_MANIFEST = {"expected_event_count", "expected_head_sha256", "manifest_recorded_at_ms"}
_KINDS = {"SUBMITTED", "ACCEPTED", "FILL", "CANCEL_REQUESTED", "CANCELED", "REJECTED", "EXPIRED"}
_IDENTITY = ("provider", "venue", "account_alias", "instrument", "client_order_id")


def _exact(value, keys, name):
    if type(value) is not dict or set(value) != keys:
        raise ValueError("Invalid " + name + " schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _ms(value):
    return type(value) is int and 0 <= value <= _MAX_MS


def _qty(value, zero=True):
    return type(value) is int and (0 if zero else 1) <= value <= 1_000_000


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _validate_scope(scope):
    _exact(scope, _SCOPE, "order scope")
    if (not all(_id(scope[k]) for k in _IDENTITY)
            or scope["side"] not in ("BUY", "SELL")
            or not _qty(scope["requested_contracts"], zero=False)
            or not _ms(scope["submitted_at_ms"])
            or not _ms(scope["as_of_ms"])
            or scope["submitted_at_ms"] > scope["as_of_ms"]
            or not _sha(scope["intent_sha256"])):
        raise ValueError("Invalid order scope or source identity")


def _validate_event(scope, event):
    _exact(event, _EVENT, "order receipt")
    if (not all(event[k] == scope[k] for k in _IDENTITY)
            or not _id(event["event_id"])
            or type(event["sequence"]) is not int
            or not (1 <= event["sequence"] <= _MAX_EVENTS)
            or type(event["kind"]) is not str or event["kind"] not in _KINDS
            or not _ms(event["occurred_at_ms"])
            or not _ms(event["received_at_ms"])
            or not (scope["submitted_at_ms"] <= event["occurred_at_ms"]
                    <= event["received_at_ms"] <= scope["as_of_ms"])
            or not _qty(event["contracts"])
            or not _sha(event["receipt_sha256"])
            or not _sha(event["previous_event_sha256"])):
        raise ValueError("Invalid receipt source, timing, quantity or hash")
    if event["kind"] == "FILL":
        if event["contracts"] == 0 or not _id(event["broker_order_id"]):
            raise ValueError("Fill requires positive quantity and broker ID")
    elif event["contracts"] != 0:
        raise ValueError("Only FILL may declare contracts")
    if event["kind"] in ("SUBMITTED", "REJECTED"):
        if event["broker_order_id"] is not None:
            raise ValueError("Submission/rejection cannot declare broker ID")
    elif event["broker_order_id"] is not None and not _id(event["broker_order_id"]):
        raise ValueError("Invalid broker order ID")


def fingerprint_demo_order_event(scope, event):
    """Calculate an unsigned, deterministic event fingerprint; not authentication."""
    _validate_scope(scope)
    _validate_event(scope, event)
    return _hash({"protocol": _PROTOCOL, "intent_sha256": scope["intent_sha256"],
                  "event": event})


def replay_declared_demo_order_receipts(scope, events, manifest):
    """Replay bounded receipts with a complete *declared* sequence/head manifest.

    Exact duplicate delivery of an identical sequence/event is idempotent.
    Conflicting retries, gaps, unknown outcomes, late fills and missing receipts
    fail closed. A successful replay never proves no actual broker exposure.
    """
    _validate_scope(scope)
    _exact(manifest, _MANIFEST, "replay manifest")
    if (not _qty(manifest["expected_event_count"], zero=False)
            or manifest["expected_event_count"] > _MAX_EVENTS
            or not _sha(manifest["expected_head_sha256"])
            or not _ms(manifest["manifest_recorded_at_ms"])
            or manifest["manifest_recorded_at_ms"] > scope["as_of_ms"]):
        raise ValueError("Invalid declared manifest")
    if type(events) is not list or not (1 <= len(events) <= _MAX_EVENTS * 2):
        raise ValueError("Missing or unbounded receipt population")

    unique = []
    seen_seq = {}
    seen_ids = set()
    duplicates = 0
    for event in events:
        _validate_event(scope, event)
        seq = event["sequence"]
        if seq in seen_seq:
            if event != seen_seq[seq]:
                raise ValueError("Conflicting receipt retry at sequence")
            duplicates += 1
            continue
        if seq != len(unique) + 1:
            raise ValueError("Missing, reordered or nonconsecutive receipt sequence")
        if event["event_id"] in seen_ids:
            raise ValueError("Reused receipt event ID")
        seen_ids.add(event["event_id"])
        seen_seq[seq] = event
        unique.append(event)
    if len(unique) != manifest["expected_event_count"]:
        raise ValueError("Incomplete receipt population versus declared manifest")

    previous = _ZERO
    previous_occurred = previous_received = -1
    accepted = cancel_requested = terminal = False
    broker_id = None
    filled = 0
    terminal_kind = None
    for index, event in enumerate(unique):
        if event["previous_event_sha256"] != previous:
            raise ValueError("Broken receipt hash chain")
        if (event["occurred_at_ms"] < previous_occurred
                or event["received_at_ms"] < previous_received):
            raise ValueError("Late/out-of-order broker event requires reconciliation")
        if terminal:
            raise ValueError("Event after terminal receipt requires reconciliation")
        kind = event["kind"]
        current_id = event["broker_order_id"]
        if index == 0:
            if kind != "SUBMITTED" or event["occurred_at_ms"] != scope["submitted_at_ms"]:
                raise ValueError("First receipt must be matching submission")
        elif kind == "SUBMITTED":
            raise ValueError("Duplicate submission with distinct sequence")
        elif kind == "ACCEPTED":
            if accepted or cancel_requested or filled or not _id(current_id):
                raise ValueError("Invalid broker acceptance transition")
            accepted, broker_id = True, current_id
        elif kind == "FILL":
            if not accepted or current_id != broker_id or filled == scope["requested_contracts"]:
                raise ValueError("Unacknowledged, cross-order or excessive fill")
            filled += event["contracts"]
            if filled > scope["requested_contracts"]:
                raise ValueError("Overfilled declared order")
        elif kind == "CANCEL_REQUESTED":
            if cancel_requested or filled == scope["requested_contracts"]:
                raise ValueError("Duplicate/late cancel request")
            if current_id != (broker_id if accepted else None):
                raise ValueError("Cancel request broker identity mismatch")
            cancel_requested = True
        elif kind == "CANCELED":
            if not accepted or not cancel_requested or current_id != broker_id or filled == scope["requested_contracts"]:
                raise ValueError("Cancellation lacks request/ack or has complete fill")
            terminal, terminal_kind = True, kind
        elif kind == "REJECTED":
            if accepted or cancel_requested or filled or current_id is not None:
                raise ValueError("Rejection contradicts prior broker state")
            terminal, terminal_kind = True, kind
        elif kind == "EXPIRED":
            if current_id != (broker_id if accepted else None) or filled == scope["requested_contracts"]:
                raise ValueError("Expiry contradicts broker identity or full fill")
            terminal, terminal_kind = True, kind
        previous = fingerprint_demo_order_event(scope, event)
        previous_occurred, previous_received = event["occurred_at_ms"], event["received_at_ms"]
    if manifest["manifest_recorded_at_ms"] < previous_received:
        raise ValueError("Manifest predates its last declared receipt")
    if previous != manifest["expected_head_sha256"]:
        raise ValueError("Receipt head differs from declared manifest")
    if filled == scope["requested_contracts"]:
        status = "DECLARED_FULL_FILL_UNVERIFIED"
    elif terminal_kind:
        status = "DECLARED_" + terminal_kind + "_EXPOSURE_UNVERIFIED"
    elif cancel_requested:
        status = "CANCEL_PENDING_EXPOSURE_UNKNOWN"
    elif accepted:
        status = "ACCEPTED_EXPOSURE_UNKNOWN"
    else:
        status = "SUBMISSION_EXPOSURE_UNKNOWN"
    return {"coverage": "SELF_DECLARED_UNAUTHENTICATED_RECEIPTS_ONLY",
            "status": status, "client_order_id": scope["client_order_id"],
            "broker_order_id": broker_id, "declared_filled_contracts": filled,
            "declared_remaining_contracts": scope["requested_contracts"] - filled,
            "unique_receipts": len(unique), "duplicate_deliveries_ignored": duplicates,
            "head_sha256": previous, "manual_broker_reconciliation_required": True,
            "may_execute_demo_order": False, "may_execute_real_order": False,
            "warnings": ["Receipt hashes and population manifest are self-declared, not authenticated broker evidence.",
                         "A replayed cancellation, rejection or expiry does not prove zero exposure.",
                         "Late/missing fills, crashes and incomplete account snapshots require external reconciliation.",
                         "No durable store, broker API, order sender, financing or realized P&L is provided."]}
