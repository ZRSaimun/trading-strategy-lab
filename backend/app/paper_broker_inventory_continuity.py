"""Disconnected continuity diagnostic for two declared broker inventory snapshots.

The caller controls every field, including the clock and both checkpoints.
This read-only preflight is not authenticated broker reconciliation, does not
release UNKNOWN attempts, and never authorizes any paper or live order.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.paper_broker_inventory_census import (
    MAX_PAGES,
    MAX_ORDERS,
    MAX_FILLS,
    _STATUSES,
    _id,
    _ms,
    _object,
    _qty,
    inspect_declared_inventory,
)

_SNAPSHOT_FIELDS = {"broker", "account_alias", "snapshot_id", "sequence",
                    "observed_at_ms", "received_at_ms", "pages"}
_PAGE_FIELDS = {"snapshot_id", "index", "total_pages", "complete", "orders"}


def _prior_metadata(previous: Any, now: int, max_transport_lag_ms: int) -> tuple[dict, set[str]]:
    """Validate bounded checkpoint metadata, not authenticity or order contents."""
    prev = _object(previous, _SNAPSHOT_FIELDS, "previous snapshot")
    for key in ("broker", "account_alias", "snapshot_id"):
        _id(prev[key], f"previous {key}")
    seq = _ms(prev["sequence"], "previous sequence")
    if seq == 0:
        raise ValueError("Invalid previous sequence")
    observed = _ms(prev["observed_at_ms"], "previous observation")
    received = _ms(prev["received_at_ms"], "previous receipt")
    pages = prev["pages"]
    if type(pages) is not list or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("Invalid previous page population")
    failures: set[str] = set()
    if not observed <= received <= now:
        failures.add("previous_snapshot_clock_invalid")
    elif received - observed > max_transport_lag_ms:
        # A complete-looking earlier checkpoint can still be delayed beyond
        # the same caller-declared transport policy used for current evidence.
        failures.add("previous_snapshot_transport_lag")
    total_orders = 0
    seen_client_ids: set[str] = set()
    seen_broker_order_ids: set[str] = set()
    seen_fill_ids: set[str] = set()
    total_fills = 0
    for index, raw in enumerate(pages):
        page = _object(raw, _PAGE_FIELDS, "previous page")
        if (_id(page["snapshot_id"], "previous page snapshot ID") != prev["snapshot_id"]
                or _ms(page["index"], "previous page index") != index
                or _ms(page["total_pages"], "previous page count") != len(pages)
                or page["complete"] is not True):
            failures.add("previous_page_census_incomplete")
        if type(page["orders"]) is not list or len(page["orders"]) > MAX_ORDERS:
            raise ValueError("Invalid previous page orders")
        total_orders += len(page["orders"])
        if total_orders > MAX_ORDERS:
            raise ValueError("Previous order population exceeds bound")
        # A caller-declared prior page cannot establish continuity when its
        # order identities are ambiguous, even if page counters look complete.
        # This is a shape/uniqueness check, not broker receipt authentication.
        for raw_order in page["orders"]:
            row = _object(raw_order, {"client_order_id", "broker_order_id",
                                     "instrument", "side", "quantity", "status",
                                     "filled_quantity", "fills"}, "previous broker order")
            client_id = _id(row["client_order_id"], "previous client order ID")
            broker_id = _id(row["broker_order_id"], "previous broker order ID")
            if client_id in seen_client_ids or broker_id in seen_broker_order_ids:
                failures.add("previous_duplicate_order_identity")
            seen_client_ids.add(client_id)
            seen_broker_order_ids.add(broker_id)
            # Prior inventory must be internally coherent too. A unique order
            # ID alone cannot establish continuity if its fills are duplicated,
            # future-dated, or inconsistent with the declared order status.
            _id(row["instrument"], "previous instrument")
            if type(row["side"]) is not str or row["side"] not in ("BUY", "SELL"):
                raise ValueError("Invalid previous order side")
            quantity = _qty(row["quantity"], "previous order quantity", positive=True)
            filled = _qty(row["filled_quantity"], "previous filled quantity")
            status = row["status"]
            if type(status) is not str or status not in _STATUSES:
                raise ValueError("Invalid previous order status")
            fills = row["fills"]
            if type(fills) is not list or len(fills) > MAX_FILLS:
                raise ValueError("Invalid previous fill population")
            total_fills += len(fills)
            if total_fills > MAX_FILLS:
                raise ValueError("Previous fill population exceeds bound")
            sum_fills = Decimal(0)
            for raw_fill in fills:
                fill = _object(raw_fill, {"fill_id", "quantity", "filled_at_ms"},
                               "previous fill")
                fill_id = _id(fill["fill_id"], "previous fill ID")
                amount = _qty(fill["quantity"], "previous fill quantity", positive=True)
                filled_at = _ms(fill["filled_at_ms"], "previous fill time")
                if fill_id in seen_fill_ids:
                    failures.add("previous_duplicate_fill_identity")
                seen_fill_ids.add(fill_id)
                sum_fills += amount
                if filled_at > observed:
                    failures.add("previous_fill_after_observation")
            if sum_fills != filled or filled > quantity:
                failures.add("previous_fill_quantity_reconciliation")
            if (status == "FILLED" and filled != quantity
                    or status in ("REJECTED", "CANCELLED", "OPEN") and filled != 0
                    or status == "PARTIAL" and not 0 < filled < quantity):
                failures.add("previous_status_quantity_reconciliation")
    return prev, failures


def inspect_declared_inventory_continuity(
    expected: dict, previous: dict | None, current: dict, now_ms: int,
) -> dict[str, Any]:
    """Hold on replay, missing checkpoint, gaps or regressed broker snapshots.

    The current inventory is fully checked by the existing census. Previous
    snapshot metadata is checked only for structural/chronological consistency;
    it is NOT authenticated or independently proven complete. A clean result
    is always unverified and cannot clear any UNKNOWN submission.
    """
    now = _ms(now_ms, "evaluation time")
    census = inspect_declared_inventory(expected, current, now)
    failures = {f"current_inventory:{reason}" for reason in census["failed_checks"]}
    if previous is None:
        failures.add("missing_prior_inventory_checkpoint")
    else:
        prev, prior_failures = _prior_metadata(
            previous, now, expected["max_transport_lag_ms"]
        )
        failures.update(prior_failures)
        if (prev["broker"], prev["account_alias"]) != (
            expected["broker"], expected["account_alias"]
        ):
            failures.add("previous_account_identity")
        if current["snapshot_id"] == prev["snapshot_id"]:
            failures.add("snapshot_id_reused")
        if current["sequence"] <= prev["sequence"]:
            failures.add("snapshot_sequence_not_advanced")
        elif current["sequence"] != prev["sequence"] + 1:
            failures.add("snapshot_sequence_gap")
        if current["observed_at_ms"] <= prev["observed_at_ms"]:
            failures.add("snapshot_observation_not_advanced")
        # An adjacent sequence is not enough if its observation window is stale.
        # This deliberately conservative caller-declared cadence bound is not
        # provider evidence and must not be used to authorize orders.
        if (current["observed_at_ms"] > prev["observed_at_ms"]
                and current["observed_at_ms"] - prev["observed_at_ms"]
                > expected["max_snapshot_age_ms"]):
            failures.add("snapshot_observation_gap_exceeds_freshness_window")
        if current["received_at_ms"] <= prev["received_at_ms"]:
            failures.add("snapshot_receipt_not_advanced")
        if current["observed_at_ms"] <= prev["received_at_ms"]:
            failures.add("snapshot_delivery_overlap")
    return {
        "status": "HOLD_INVENTORY_CONTINUITY" if failures else "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED",
        "failed_checks": sorted(failures),
        "current_inventory_status": census["status"],
        "current_inventory_failed_checks": census["failed_checks"],
        "prior_checkpoint_authenticated": False,
        "broker_authenticated": False,
        "inventory_continuity_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
