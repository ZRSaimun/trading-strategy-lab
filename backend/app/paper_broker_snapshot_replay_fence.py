"""Disconnected, fail-closed comparison of two declared broker inventory snapshots.

Neither snapshot is authenticated. This diagnostic NEVER clears UNKNOWN attempts,
submits orders, or treats a caller-assigned sequence as broker proof.
"""
from __future__ import annotations

from typing import Any
from decimal import Decimal

from app.paper_broker_inventory_census import inspect_declared_inventory

_TERMINAL = frozenset({"FILLED", "REJECTED", "CANCELLED"})
_ALLOWED_PREVIOUS_FAILURES = frozenset({"unresolved_order_state"})


def _orders(snapshot: dict) -> dict[str, dict]:
    return {order["client_order_id"]: order
            for page in snapshot["pages"] for order in page["orders"]}


def inspect_declared_snapshot_transition(expected: dict, previous: dict,
                                         current: dict, previous_now_ms: int,
                                         now_ms: int) -> dict[str, Any]:
    """Conservatively detect chronology, replay, and order/fill regression.

    The caller must supply an independently persisted previous snapshot. Both
    snapshots are fully revalidated by the underlying bounded census. Even a
    clean transition is a diagnostic candidate, never an execution permission.
    """
    earlier = inspect_declared_inventory(expected, previous, previous_now_ms)
    later = inspect_declared_inventory(expected, current, now_ms)
    failures: set[str] = set()
    if type(previous_now_ms) is not int or type(now_ms) is not int or previous_now_ms >= now_ms:
        failures.add("trusted_clock_order")
    if (previous["broker"], previous["account_alias"]) != (current["broker"], current["account_alias"]):
        failures.add("snapshot_account_changed")
    if previous["snapshot_id"] == current["snapshot_id"]:
        failures.add("snapshot_id_reused")
    if current["sequence"] <= previous["sequence"]:
        failures.add("snapshot_sequence_replay")
    elif current["sequence"] != previous["sequence"] + 1:
        # Skipped caller checkpoints may conceal intervening broker changes.
        failures.add("snapshot_sequence_gap")
    if (current["observed_at_ms"] <= previous["observed_at_ms"]
            or current["received_at_ms"] <= previous["received_at_ms"]):
        failures.add("snapshot_time_regression")
    # An observation taken before the previous snapshot was received leaves
    # an ambiguous overlap. Preserve quarantine rather than trusting ordering.
    if current["observed_at_ms"] <= previous["received_at_ms"]:
        failures.add("snapshot_observation_overlap")
    if current["observed_at_ms"] <= previous_now_ms:
        # The next observation must follow the prior trusted checkpoint.
        failures.add("snapshot_observation_precedes_prior_check")
    if set(earlier["failed_checks"]) - _ALLOWED_PREVIOUS_FAILURES:
        failures.add("previous_census_invalid")
    if later["failed_checks"]:
        failures.add("current_census_invalid")

    old = _orders(previous)
    new = _orders(current)
    for cid in old.keys() & new.keys():
        a, b = old[cid], new[cid]
        if a["broker_order_id"] != b["broker_order_id"]:
            failures.add("broker_order_identity_changed")
        if a["status"] in _TERMINAL and a["status"] != b["status"]:
            failures.add("terminal_status_changed")
        if Decimal(b["filled_quantity"]) < Decimal(a["filled_quantity"]):
            failures.add("filled_quantity_decreased")
        old_fills = {f["fill_id"]: f for f in a["fills"]}
        new_fills = {f["fill_id"]: f for f in b["fills"]}
        for fid, fill in old_fills.items():
            if fid not in new_fills:
                failures.add("previous_fill_disappeared")
            elif (fill["filled_at_ms"] != new_fills[fid]["filled_at_ms"]
                  or Decimal(fill["quantity"]) != Decimal(new_fills[fid]["quantity"])):
                failures.add("previous_fill_mutated")
        # A newly disclosed fill dated at/before the earlier observation
        # indicates a retroactive correction or incomplete prior inventory.
        # Neither case is evidence that an UNKNOWN order may be retried.
        for fid, fill in new_fills.items():
            if fid not in old_fills:
                if fill["filled_at_ms"] <= previous["observed_at_ms"]:
                    failures.add("retroactive_fill_appearance")
                # A fill first disclosed after the trusted prior census but
                # timestamped at/before that check means the prior checkpoint
                # was already incomplete when accepted. Hold even if the fill
                # occurred after the previous broker observation.
                if fill["filled_at_ms"] <= previous_now_ms:
                    failures.add("fill_predates_prior_trusted_check")
    if set(old) != set(new):
        failures.add("snapshot_order_population_changed")
    return {
        "status": ("HOLD_RECONCILIATION" if failures
                   else "DECLARED_TRANSITION_CANDIDATE_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "previous_census_failed_checks": earlier["failed_checks"],
        "current_census_failed_checks": later["failed_checks"],
        "broker_authenticated": False,
        "snapshot_completeness_authenticated": False,
        "terminal_receipts_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
