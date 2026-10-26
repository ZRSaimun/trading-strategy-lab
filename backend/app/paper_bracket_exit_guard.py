"""Disconnected PAPER bracket/exit inventory preflight; never sends an order.

All snapshots, acknowledgements, prices and inventory-completeness claims are
caller-declared and unauthenticated. Structural consistency is NOT broker proof.
"""
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import re

_MAX_MS = 8_640_000_000_000_000
_MAX_AGE_MS = 3000  # Hard ceiling, not a caller-controlled safety relaxation.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_NUM = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_POSITION = {"account", "provider", "venue", "instrument", "position_id",
             "side", "open_quantity", "entry_price", "stop_price",
             "stressed_exit_price", "point_value_cash", "exit_cost_cash",
             "max_position_loss_cash", "snapshot_at_ms",
             "complete_order_inventory", "inventory_revision"}
_ORDER = {"order_id", "position_id", "account", "provider", "venue",
          "instrument", "role", "side", "status", "quantity",
          "filled_quantity", "trigger_price", "reduce_only",
          "oco_group", "ack_at_ms"}
_STATUSES = {"SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED",
             "CANCEL_PENDING", "CANCELED", "REPLACE_PENDING",
             "REJECTED", "EXPIRED"}


def _shape(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid " + label + " schema")
    return value


def _id(value, label):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("Invalid " + label)
    return value


def _cash(value, label, *, zero=False):
    if type(value) is not str or not _NUM.fullmatch(value):
        raise ValueError("Invalid " + label + ": use bounded decimal strings")
    result = Decimal(value)
    if result < 0 or (not zero and result == 0):
        raise ValueError("Invalid " + label + ": nonpositive")
    return result


def _time(value, label):
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError("Invalid " + label)
    return value


def review_paper_exit_bracket(position, orders, *, server_now_ms):
    """Read-only stop/target coverage review; ALWAYS returns execution denied.

    Reject malformed data; return diagnostic reasons for structurally valid
    but unsafe inventories. Caller must independently authenticate broker
    snapshots, fills, reduce-only and OCO semantics before any real use.
    """
    now = _time(server_now_ms, "server time")
    p = _shape(position, _POSITION, "position")
    if type(orders) is not list or len(orders) > 100:
        raise ValueError("Invalid bounded exit-order population")
    for field in ("account", "provider", "venue", "instrument", "position_id"):
        _id(p[field], field)
    if p["side"] not in ("LONG", "SHORT"):
        raise ValueError("Invalid position side")
    if type(p["complete_order_inventory"]) is not bool:
        raise ValueError("Invalid inventory completeness flag")
    if type(p["inventory_revision"]) is not int or not 1 <= p["inventory_revision"] <= 2**53 - 1:
        raise ValueError("Invalid inventory revision")
    snapshot = _time(p["snapshot_at_ms"], "snapshot timestamp")
    amounts = {key: _cash(p[key], key, zero=key == "exit_cost_cash")
               for key in ("open_quantity", "entry_price", "stop_price",
                           "stressed_exit_price", "point_value_cash",
                           "exit_cost_cash", "max_position_loss_cash")}
    entry, stop, stressed = (amounts[k] for k in
                            ("entry_price", "stop_price", "stressed_exit_price"))
    if p["side"] == "LONG" and not stressed < stop < entry:
        raise ValueError("Long exit stress must be below stop below entry")
    if p["side"] == "SHORT" and not entry < stop < stressed:
        raise ValueError("Short exit stress must exceed stop above entry")
    reasons = []
    if snapshot > now or now - snapshot > _MAX_AGE_MS:
        reasons.append("STALE_OR_FUTURE_INVENTORY")
    if not p["complete_order_inventory"]:
        reasons.append("INCOMPLETE_ORDER_INVENTORY")
    seen = set()
    active_stops, active_targets = [], []
    for raw in orders:
        o = _shape(raw, _ORDER, "exit order")
        _id(o["order_id"], "order ID")
        _id(o["oco_group"], "OCO group")
        if o["order_id"] in seen:
            raise ValueError("Duplicate exit order ID")
        seen.add(o["order_id"])
        for field in ("account", "provider", "venue", "instrument", "position_id"):
            if _id(o[field], field) != p[field]:
                raise ValueError("Cross-account/source/position exit order")
        if o["role"] not in ("STOP", "TARGET") or o["status"] not in _STATUSES:
            raise ValueError("Invalid exit role/status")
        if o["side"] != ("SELL" if p["side"] == "LONG" else "BUY"):
            raise ValueError("Exit side would increase rather than reduce exposure")
        if type(o["reduce_only"]) is not bool:
            raise ValueError("Invalid reduce-only declaration")
        qty = _cash(o["quantity"], "exit quantity")
        filled = _cash(o["filled_quantity"], "filled quantity", zero=True)
        trigger = _cash(o["trigger_price"], "exit trigger")
        ack = _time(o["ack_at_ms"], "ack timestamp")
        if filled > qty:
            raise ValueError("Exit fills exceed submitted quantity")
        if ack > snapshot:
            reasons.append("ACK_AFTER_INVENTORY_SNAPSHOT")
        if o["status"] in ("ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED") and ack == 0:
            reasons.append("MISSING_ORDER_ACK")
        if filled > 0 or o["status"] in ("PARTIALLY_FILLED", "FILLED"):
            reasons.append("UNRECONCILED_EXIT_FILLS")
        if o["status"] in ("SUBMITTED", "CANCEL_PENDING", "REPLACE_PENDING"):
            reasons.append("UNRESOLVED_ORDER_TRANSITION")
        if not o["reduce_only"]:
            reasons.append("REDUCE_ONLY_UNVERIFIED")
        if o["role"] == "STOP" and trigger != stop:
            reasons.append("STOP_TRIGGER_MISMATCH")
        if o["role"] == "TARGET" and not (
            trigger > entry if p["side"] == "LONG" else trigger < entry
        ):
            reasons.append("TARGET_NOT_PROFIT_SIDE")
        if o["status"] == "ACKNOWLEDGED" and filled == 0:
            (active_stops if o["role"] == "STOP" else active_targets).append((o, qty))
    if len(active_stops) != 1:
        reasons.append("MISSING_OR_MULTIPLE_ACTIVE_STOPS")
    else:
        stop_order, stop_qty = active_stops[0]
        if stop_qty != amounts["open_quantity"]:
            reasons.append("STOP_COVERAGE_NOT_EXACT")
        if any(target["oco_group"] != stop_order["oco_group"]
               for target, _ in active_targets):
            reasons.append("OCO_GROUP_MISMATCH")
    if len(active_targets) > 1:
        reasons.append("MULTIPLE_ACTIVE_TARGETS")
    if any(qty > amounts["open_quantity"] for _, qty in active_targets):
        reasons.append("TARGET_OVER_COVERAGE")
    with localcontext() as ctx:
        ctx.prec = 60
        stressed_loss = (amounts["open_quantity"] * abs(entry - stressed)
                         * amounts["point_value_cash"] + amounts["exit_cost_cash"])
    if stressed_loss > amounts["max_position_loss_cash"]:
        reasons.append("STRESSED_LOSS_EXCEEDS_CAP")
    fingerprint = sha256(json.dumps({"position": p, "orders": orders, "now_ms": now},
                                    sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()
    return {
        "status": "HOLD_RECONCILIATION",
        "declared_bracket_consistent": not reasons,
        "reasons": sorted(set(reasons)),
        "declared_stressed_loss_cash": format(stressed_loss, "f"),
        "review_sha256": fingerprint,
        "broker_inventory_authenticated": False,
        "broker_acknowledgements_verified": False,
        "broker_oco_reduce_only_verified": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
    }
