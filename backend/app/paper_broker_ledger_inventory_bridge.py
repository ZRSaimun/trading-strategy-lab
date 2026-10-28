"""Read-only cross-check between a declared UNKNOWN ledger summary and broker census.

This is a conservative integration *preflight*, not a broker/ledger trust
establishment, terminal reconciliation, order authorization, or database read.
The summary is supplied by the caller; the independently authenticated ledger
and provider evidence needed for execution do not exist in this module.
"""
from __future__ import annotations

import re
from typing import Any

from app.paper_broker_inventory_census import MAX_MS, MAX_ORDERS
from app.paper_broker_reconciliation_context_anchor import (
    inspect_declared_reconciliation_context_anchors,
)
from app.paper_broker_snapshot_chain_audit import MAX_CHECKPOINT_GAP_MS

_SHA256 = re.compile(r"[0-9a-f]{64}\\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\\Z")
_TERMINAL = frozenset({
    "RECONCILED_FILLED", "RECONCILED_REJECTED", "RECONCILED_CANCELLED",
})
_STATUSES = _TERMINAL | {"PREPARED", "ATTEMPT_UNKNOWN"}
_MAX_LEDGER_EVENTS = 10_000
_LEDGER_KEYS = {
    "schema", "event_count", "order_count", "audit_tip_sha256",
    "last_recorded_at_ms", "orders", "status", "may_submit_paper_order",
    "may_submit_real_order", "warning",
}
_ROW_KEYS = {"broker", "account_alias", "client_order_id", "status"}


def _sha(value: Any, name: str) -> str:
    if (type(value) is not str or not _SHA256.fullmatch(value)
            or value == "0" * 64):
        raise ValueError(f"Invalid {name}")
    return value


def _id(value: Any, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def inspect_declared_ledger_inventory_bridge(
    expected: dict,
    snapshots: list[dict],
    check_times_ms: list[int],
    prior_snapshot_digests: list[str],
    prior_chain_digest: str,
    prior_context_digest: str,
    ledger_summary: dict,
    prior_ledger_tip_sha256: str,
    max_checkpoint_gap_ms: int = MAX_CHECKPOINT_GAP_MS,
) -> dict[str, Any]:
    """Compare one account's UNKNOWN IDs with a caller-supplied ledger audit.

    The original ledger must be audited separately. A matching local audit tip
    and consistent declared snapshots do not authenticate a broker, prove
    immutable custody, bind intent SHA values, or permit clearing UNKNOWN.
    """
    _sha(prior_ledger_tip_sha256, "prior ledger tip")
    if type(ledger_summary) is not dict or set(ledger_summary) != _LEDGER_KEYS:
        raise ValueError("Invalid ledger summary schema")
    if ledger_summary["schema"] != "paper-submission-attempt-ledger-v1":
        raise ValueError("Invalid ledger schema version")
    if (ledger_summary["status"] != "HOLD_RECONCILIATION"
            or ledger_summary["may_submit_paper_order"] is not False
            or ledger_summary["may_submit_real_order"] is not False):
        raise ValueError("Ledger summary contains an unsafe execution claim")
    if type(ledger_summary["warning"]) is not str or not ledger_summary["warning"]:
        raise ValueError("Invalid ledger summary warning")
    count = ledger_summary["event_count"]
    if type(count) is not int or not 1 <= count <= _MAX_LEDGER_EVENTS:
        raise ValueError("Invalid ledger event count")
    stamp = ledger_summary["last_recorded_at_ms"]
    if type(stamp) is not int or not 0 <= stamp <= MAX_MS:
        raise ValueError("Invalid ledger last event time")
    tip = _sha(ledger_summary["audit_tip_sha256"], "ledger audit tip")
    rows = ledger_summary["orders"]
    if type(rows) is not list or not 1 <= len(rows) <= _MAX_LEDGER_EVENTS:
        raise ValueError("Invalid ledger order population")
    if (type(ledger_summary["order_count"]) is not int
            or ledger_summary["order_count"] != len(rows)
            or count < len(rows)):
        raise ValueError("Ledger order/event counts are inconsistent")

    failures: set[str] = set()
    if tip != prior_ledger_tip_sha256:
        failures.add("ledger_audit_tip_mismatch")
    target = (expected["broker"], expected["account_alias"])
    expected_ids = {row["client_order_id"] for row in expected["unresolved_orders"]}
    if not 1 <= len(expected_ids) <= MAX_ORDERS:
        raise ValueError("Invalid expected UNKNOWN population")
    seen: set[tuple[str, str, str]] = set()
    unknown_ids: set[str] = set()
    for row in rows:
        if type(row) is not dict or set(row) != _ROW_KEYS:
            raise ValueError("Invalid ledger order row")
        broker = _id(row["broker"], "ledger broker")
        account = _id(row["account_alias"], "ledger account")
        order_id = _id(row["client_order_id"], "ledger client order ID")
        if type(row["status"]) is not str or row["status"] not in _STATUSES:
            raise ValueError("Invalid ledger order state")
        key = (broker, account, order_id)
        if key in seen:
            raise ValueError("Duplicate ledger order identity")
        seen.add(key)
        if (broker, account) == target and row["status"] == "ATTEMPT_UNKNOWN":
            unknown_ids.add(order_id)
    if unknown_ids != expected_ids:
        failures.add("ledger_unknown_population_mismatch")
    # The ledger records PREPARED and ATTEMPT_UNKNOWN for each UNKNOWN order.
    if count < 2 * len(expected_ids):
        failures.add("ledger_event_population_insufficient")

    audit = inspect_declared_reconciliation_context_anchors(
        expected, snapshots, check_times_ms, prior_snapshot_digests,
        prior_chain_digest, prior_context_digest,
        max_checkpoint_gap_ms=max_checkpoint_gap_ms,
    )
    failures.update(audit["failed_checks"])
    return {
        "status": ("HOLD_RECONCILIATION" if failures
                   else "DECLARED_LEDGER_INVENTORY_CANDIDATE_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "ledger_order_count": len(rows),
        "expected_unknown_count": len(expected_ids),
        "ledger_authenticated": False,
        "ledger_tip_custody_authenticated": False,
        "ledger_intent_fingerprints_bound": False,
        "broker_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
