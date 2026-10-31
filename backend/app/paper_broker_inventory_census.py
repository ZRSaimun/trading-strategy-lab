"""Disconnected broker-order inventory census for UNKNOWN submission investigations.

Inputs are caller-declared and unauthenticated. This module NEVER releases an
UNKNOWN submission or authorizes paper/live orders. No HTTP, secrets, writes,
or broker adapter. Its conservative checks identify evidence gaps for review.
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

MAX_MS = 8_640_000_000_000_000
MAX_PAGES = 16
MAX_ORDERS = 256
MAX_FILLS = 2048
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_QTY = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")
_BROKERS = frozenset({"PAPER-LOCAL", "T212-INVEST-DEMO", "T212-STOCKSISA-DEMO",
                      "T212-INVEST-LIVE", "T212-STOCKSISA-LIVE"})
_TERMINAL = frozenset({"FILLED", "REJECTED", "CANCELLED"})
_STATUSES = _TERMINAL | {"OPEN", "PARTIAL"}


def _object(value: Any, keys: set[str], name: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"Invalid {name} fields")
    return value


def _id(value: Any, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _sha(value: Any) -> str:
    if type(value) is not str or not _SHA.fullmatch(value) or value == "0" * 64:
        raise ValueError("Invalid intent fingerprint")
    return value


def _ms(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_MS:
        raise ValueError(f"Invalid {name}")
    return value


def _positive_ms(value: Any, name: str) -> int:
    value = _ms(value, name)
    if not 1 <= value <= 60_000:
        raise ValueError(f"Invalid {name}")
    return value


def _qty(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not str or not _QTY.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    result = Decimal(value)
    if positive and result <= 0:
        raise ValueError(f"Invalid {name}")
    return result


def inspect_declared_inventory(expected: dict, observed: dict, now_ms: int) -> dict:
    """Read-only preflight; never equates declared snapshots with broker proof.

    'pages' must be a complete ordered snapshot of an account at one instant.
    Any missing, extra, duplicate, stale or inconsistent evidence is a HOLD.
    Schema errors raise ValueError (also fail closed). No status releases orders.
    """
    now = _ms(now_ms, "trusted now")
    e = _object(expected, {"broker", "account_alias", "max_snapshot_age_ms",
                           "max_transport_lag_ms", "unresolved_orders"}, "expected")
    o = _object(observed, {"broker", "account_alias", "snapshot_id", "sequence",
                           "observed_at_ms", "received_at_ms", "pages"}, "observed")
    broker = _id(e["broker"], "broker")
    if broker not in _BROKERS:
        raise ValueError("Unsupported broker label; no CFD execution support inferred")
    account = _id(e["account_alias"], "account")
    _id(o["broker"], "observed broker")
    _id(o["account_alias"], "observed account")
    _id(o["snapshot_id"], "snapshot ID")
    sequence = _ms(o["sequence"], "snapshot sequence")
    if sequence == 0:
        raise ValueError("Invalid snapshot sequence")
    stamp = _ms(o["observed_at_ms"], "snapshot observation")
    receipt = _ms(o["received_at_ms"], "snapshot receipt")
    max_age = _positive_ms(e["max_snapshot_age_ms"], "maximum snapshot age")
    max_lag = _positive_ms(e["max_transport_lag_ms"], "maximum transport lag")
    unresolved = e["unresolved_orders"]
    if type(unresolved) is not list or not 1 <= len(unresolved) <= MAX_ORDERS:
        raise ValueError("Invalid unresolved order population")
    expected_orders = {}
    intents = set()
    for row in unresolved:
        item = _object(row, {"client_order_id", "intent_sha", "instrument", "side",
                             "quantity", "attempted_at_ms"}, "unresolved order")
        cid = _id(item["client_order_id"], "client order ID")
        digest = _sha(item["intent_sha"])
        symbol = _id(item["instrument"], "instrument")
        side = item["side"]
        if side not in ("BUY", "SELL") or type(side) is not str:
            raise ValueError("Invalid order side")
        quantity = _qty(item["quantity"], "intent quantity", positive=True)
        attempt = _ms(item["attempted_at_ms"], "attempt time")
        if cid in expected_orders or digest in intents:
            raise ValueError("Duplicate unresolved order ID or intent")
        expected_orders[cid] = (symbol, side, quantity, attempt)
        intents.add(digest)

    pages = o["pages"]
    if type(pages) is not list or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("Invalid page population")
    failures = set()
    if (o["broker"], o["account_alias"]) != (broker, account):
        failures.add("account_identity")
    if not stamp <= receipt <= now or now - stamp > max_age:
        failures.add("snapshot_freshness")
    if not stamp <= receipt <= now or receipt - stamp > max_lag:
        failures.add("snapshot_transport_lag")

    seen_orders = {}
    seen_broker_ids = set()
    seen_fill_ids = set()
    total_fills = 0
    total_orders = 0
    for index, raw_page in enumerate(pages):
        page = _object(raw_page, {"snapshot_id", "index", "total_pages",
                                  "complete", "orders"}, "page")
        if (_id(page["snapshot_id"], "page snapshot ID") != o["snapshot_id"]
                or _ms(page["index"], "page index") != index
                or _ms(page["total_pages"], "page count") != len(pages)
                or page["complete"] is not True):
            failures.add("page_census_complete")
        rows = page["orders"]
        if type(rows) is not list or len(rows) > MAX_ORDERS:
            raise ValueError("Invalid page orders")
        total_orders += len(rows)
        if total_orders > MAX_ORDERS:
            raise ValueError("Observed order population exceeds bound")
        for raw_order in rows:
            row = _object(raw_order, {"client_order_id", "broker_order_id", "instrument",
                                      "side", "quantity", "status", "filled_quantity",
                                      "fills"}, "broker order")
            cid = _id(row["client_order_id"], "observed client ID")
            broker_id = _id(row["broker_order_id"], "broker order ID")
            symbol = _id(row["instrument"], "observed instrument")
            side = row["side"]
            if type(side) is not str or side not in ("BUY", "SELL"):
                raise ValueError("Invalid observed side")
            qty = _qty(row["quantity"], "observed quantity", positive=True)
            filled = _qty(row["filled_quantity"], "filled quantity")
            status = row["status"]
            if type(status) is not str or status not in _STATUSES:
                raise ValueError("Invalid observed status")
            if cid in seen_orders or broker_id in seen_broker_ids:
                failures.add("duplicate_order_identity")
            seen_broker_ids.add(broker_id)
            seen_orders[cid] = (symbol, side, qty, status, filled)
            fills = row["fills"]
            if type(fills) is not list or len(fills) > MAX_FILLS:
                raise ValueError("Invalid fill population")
            total_fills += len(fills)
            if total_fills > MAX_FILLS:
                raise ValueError("Fill population exceeds bound")
            sum_fills = Decimal(0)
            for raw_fill in fills:
                f = _object(raw_fill, {"fill_id", "quantity", "filled_at_ms"}, "fill")
                fid = _id(f["fill_id"], "fill ID")
                amount = _qty(f["quantity"], "fill quantity", positive=True)
                when = _ms(f["filled_at_ms"], "fill time")
                if fid in seen_fill_ids:
                    failures.add("duplicate_fill_identity")
                seen_fill_ids.add(fid)
                sum_fills += amount
                if when > stamp or (cid in expected_orders and when < expected_orders[cid][3]):
                    failures.add("fill_timing")
            if sum_fills != filled or filled > qty:
                failures.add("fill_quantity_reconciliation")
            if (status == "FILLED" and filled != qty
                    or status in ("REJECTED", "CANCELLED", "OPEN") and filled != 0
                    or status == "PARTIAL" and not 0 < filled < qty):
                failures.add("status_quantity_reconciliation")
            if cid in expected_orders:
                expected_symbol, expected_side, expected_qty, attempted_at = expected_orders[cid]
                if (symbol, side, qty) != (expected_symbol, expected_side, expected_qty):
                    failures.add("order_intent_mismatch")
                if stamp < attempted_at or attempted_at > now:
                    failures.add("snapshot_precedes_attempt")
            else:
                failures.add("unexpected_account_order")
            if status not in _TERMINAL:
                failures.add("unresolved_order_state")
    if set(seen_orders) != set(expected_orders):
        failures.add("order_population_complete")
    return {
        "status": "HOLD_RECONCILIATION" if failures else "DECLARED_TERMINAL_CANDIDATE_UNVERIFIED",
        "failed_checks": sorted(failures),
        "unresolved_order_count": len(expected_orders),
        "observed_order_count": len(seen_orders),
        "observed_fill_count": total_fills,
        "broker_authenticated": False,
        "snapshot_completeness_authenticated": False,
        "terminal_receipts_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
