"""Disconnected broker-reconnect quarantine for hypothetical PAPER account snapshots.

Caller-declared evidence is not authenticated. This module NEVER authorizes
orders, releases risk reservations, or verifies that a broker honored a stop.
"""
import hashlib
import json
import re

_MAX_MS = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_SNAPSHOT_KEYS = frozenset({
    "broker", "account_id", "feed", "connection_epoch", "snapshot_revision",
    "captured_at_ms", "inventory_observed_at_ms", "quote_observed_at_ms",
    "quote_received_at_ms", "quote_sequence", "order_sequence",
    "fill_sequence", "risk_revision", "working_order_ids",
    "unknown_outcome_order_ids", "terminal_receipts",
})
_RECEIPT_KEYS = frozenset({"client_order_id", "outcome", "observed_at_ms"})
_TERMINAL = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"{name}: invalid nonnegative integer")
    return value


def _identifier(value, name):
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{name}: invalid bounded identifier")
    return value


def _ids(value, name):
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError(f"{name}: invalid bounded list")
    ids = [_identifier(v, name) for v in value]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{name}: duplicate identifier")
    return ids


def _snapshot(value):
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_KEYS:
        raise ValueError("Invalid reconnect snapshot fields")
    result = {}
    for name in ("broker", "account_id", "feed"):
        result[name] = _identifier(value[name], name)
    for name in (
        "connection_epoch", "snapshot_revision", "captured_at_ms",
        "inventory_observed_at_ms", "quote_observed_at_ms",
        "quote_received_at_ms", "quote_sequence", "order_sequence",
        "fill_sequence", "risk_revision",
    ):
        result[name] = _integer(value[name], name)
    for name in ("working_order_ids", "unknown_outcome_order_ids"):
        result[name] = _ids(value[name], name)
    if set(result["working_order_ids"]) & set(result["unknown_outcome_order_ids"]):
        raise ValueError("Working and unknown order populations overlap")
    receipts = value["terminal_receipts"]
    if not isinstance(receipts, list) or len(receipts) > 500:
        raise ValueError("Invalid bounded terminal receipt list")
    normalized = []
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
            raise ValueError("Invalid terminal receipt fields")
        order_id = _identifier(receipt["client_order_id"], "client_order_id")
        outcome = receipt["outcome"]
        if type(outcome) is not str or outcome not in _TERMINAL:
            raise ValueError("Unsupported terminal outcome")
        normalized.append({
            "client_order_id": order_id,
            "outcome": outcome,
            "observed_at_ms": _integer(receipt["observed_at_ms"], "receipt time"),
        })
    if len({r["client_order_id"] for r in normalized}) != len(normalized):
        raise ValueError("Duplicate terminal receipts")
    result["terminal_receipts"] = normalized
    if not (
        result["quote_observed_at_ms"] <= result["quote_received_at_ms"]
        <= result["captured_at_ms"]
        and result["inventory_observed_at_ms"] <= result["captured_at_ms"]
        and all(r["observed_at_ms"] <= result["captured_at_ms"] for r in normalized)
    ):
        raise ValueError("Snapshot contains impossible observation chronology")
    if len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")) > 131072:
        raise ValueError("Snapshot exceeds bounded envelope")
    return result


def evaluate_paper_reconnect(before, after, *, disconnect_at_ms, reconnected_at_ms,
                             now_ms, max_quote_age_ms=3000,
                             max_transport_lag_ms=1000,
                             max_snapshot_age_ms=5000):
    """Compare two untrusted snapshots and keep every reconnect quarantined.

    Inputs MUST be collected and checked by a future authenticated, durable
    broker adapter; passing these structural checks alone is never sufficient.
    """
    disconnect = _integer(disconnect_at_ms, "disconnect_at_ms")
    reconnect = _integer(reconnected_at_ms, "reconnected_at_ms")
    now = _integer(now_ms, "now_ms")
    for name, limit, lower, upper in (
        ("max_quote_age_ms", max_quote_age_ms, 100, 60000),
        ("max_transport_lag_ms", max_transport_lag_ms, 0, 60000),
        ("max_snapshot_age_ms", max_snapshot_age_ms, 100, 60000),
    ):
        if type(limit) is not int or not lower <= limit <= upper:
            raise ValueError(f"{name}: invalid timing limit")
    prior = _snapshot(before)
    current = _snapshot(after)
    prior_working = set(prior["working_order_ids"])
    current_working = set(current["working_order_ids"])
    receipts = {r["client_order_id"]: r for r in current["terminal_receipts"]}
    filled = any(r["outcome"] == "FILLED" for r in receipts.values())
    chronology = prior["captured_at_ms"] <= disconnect < reconnect <= now
    post_chronology = reconnect <= current["captured_at_ms"] <= now
    quote_chronology = (
        current["quote_observed_at_ms"] >= reconnect
        and current["quote_received_at_ms"] <= current["captured_at_ms"]
    )
    checks = {
        "same_broker_account_and_feed": all(
            prior[key] == current[key] for key in ("broker", "account_id", "feed")
        ),
        "connection_epoch_incremented_once": (
            current["connection_epoch"] == prior["connection_epoch"] + 1
        ),
        "snapshot_revision_advanced": (
            current["snapshot_revision"] > prior["snapshot_revision"]
        ),
        "disconnect_reconnect_chronology": chronology and post_chronology,
        "inventory_refreshed_after_reconnect": (
            post_chronology and current["inventory_observed_at_ms"] >= reconnect
        ),
        "quote_observed_after_reconnect": quote_chronology,
        "quote_sequence_advanced": current["quote_sequence"] > prior["quote_sequence"],
        "quote_fresh_at_current_time": (
            quote_chronology and post_chronology
            and now - current["quote_observed_at_ms"] <= max_quote_age_ms
        ),
        "quote_transport_delay_within_cap": (
            current["quote_received_at_ms"] - current["quote_observed_at_ms"]
            <= max_transport_lag_ms
        ),
        "snapshot_fresh_at_current_time": (
            post_chronology and now - current["captured_at_ms"] <= max_snapshot_age_ms
        ),
        "order_and_fill_sequences_monotonic": (
            current["order_sequence"] >= prior["order_sequence"]
            and current["fill_sequence"] >= prior["fill_sequence"]
        ),
        "risk_revision_unchanged_pending_review": (
            current["risk_revision"] == prior["risk_revision"]
        ),
        "no_prior_unknown_outcomes": not prior["unknown_outcome_order_ids"],
        "no_current_unknown_outcomes": not current["unknown_outcome_order_ids"],
        "prior_working_orders_accounted_for": (
            prior_working <= (current_working | set(receipts))
        ),
        "no_unexplained_new_working_orders": current_working <= prior_working,
        "terminal_receipts_only_for_prior_working": set(receipts) <= prior_working,
        "terminal_receipts_not_still_working": not (set(receipts) & current_working),
        "terminal_receipts_post_reconnect": all(
            reconnect <= r["observed_at_ms"] <= now for r in receipts.values()
        ),
        "fill_sequence_matches_declared_terminal_fills": (
            current["fill_sequence"] > prior["fill_sequence"] if filled
            else current["fill_sequence"] == prior["fill_sequence"]
        ),
    }
    payload = {
        "schema": "paper-broker-reconnect-fence-v1",
        "before": prior, "after": current,
        "disconnect_at_ms": disconnect, "reconnected_at_ms": reconnect,
        "now_ms": now,
        "max_quote_age_ms": max_quote_age_ms,
        "max_transport_lag_ms": max_transport_lag_ms,
        "max_snapshot_age_ms": max_snapshot_age_ms,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "paper-broker-reconnect-fence-v1",
        "status": "HOLD_RECONCILIATION",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "structural_checks_pass": all(checks.values()),
        "review_sha256": fingerprint,
        "broker_snapshot_authenticated": False,
        "broker_inventory_reconciled": False,
        "protective_stops_acknowledged": False,
        "risk_reservation_committed": False,
        "requires_authenticated_reconciliation": True,
        "requires_fresh_human_order_review": True,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warnings": [
            "Declared snapshots and SHA-256 are not broker authentication or signed receipts.",
            "A reconnect fences ALL order submissions until durable broker inventory, "
            "fills, stops, pending orders, and risk reservations are reconciled.",
            "Do not blindly retry orders with unknown outcomes or infer missing "
            "orders were cancelled. No broker connection or order execution exists.",
        ],
    }
