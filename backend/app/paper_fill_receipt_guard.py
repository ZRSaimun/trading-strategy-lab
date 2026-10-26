"""Disconnected, fail-closed paper fill receipt continuity and loss review.

Caller-provided snapshots are NOT broker-authenticated. This module does not
submit orders, release reservations, change stops, or mutate the database.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_MONEY = re.compile(r"(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?\Z")
_MAX_MS = 8_640_000_000_000_000
_MAX_SEQ = 2**53 - 1
_TERMINAL = frozenset({"FILLED", "CANCELED", "REJECTED"})
_STATES = frozenset({"OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "UNKNOWN"})


@dataclass(frozen=True)
class FillReceipt:
    fill_id: str
    quantity: str
    price: str
    fee_cash: str
    executed_ms: int
    received_ms: int


@dataclass(frozen=True)
class FillSnapshot:
    account_alias: str
    order_alias: str
    instrument: str
    provider: str
    venue: str
    side: str  # BUY opens a hypothetical long; SELL opens a hypothetical short
    requested_quantity: str
    protective_stop: str
    point_value_cash: str
    revision: int
    observed_ms: int
    order_status: str
    fills: tuple[FillReceipt, ...]


@dataclass(frozen=True)
class FillReviewPolicy:
    max_snapshot_age_ms: int = 5_000
    max_receipt_lag_ms: int = 10_000
    max_fills: int = 1_000
    max_total_fee_cash: str = "1000"
    max_position_loss_cash: str = "1000"


def _identity(value, label, *, symbol=False):
    if not isinstance(value, str) or not (_SYMBOL if symbol else _ID).fullmatch(value):
        raise ValueError(f"Invalid {label}")


def _integer(value, label):
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"Invalid {label}")


def _decimal(value, label, *, positive=False):
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise ValueError(f"Invalid {label}: expected bounded decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not amount.is_finite() or (positive and amount <= 0):
        raise ValueError(f"Invalid {label}")
    return amount


def _validate(snapshot, policy, now_ms):
    if not isinstance(snapshot, FillSnapshot) or not isinstance(policy, FillReviewPolicy):
        raise ValueError("Invalid snapshot or policy type")
    _integer(now_ms, "server time")
    for name in ("account_alias", "order_alias"):
        _identity(getattr(snapshot, name), name)
    for name in ("instrument", "provider", "venue"):
        _identity(getattr(snapshot, name), name, symbol=True)
    if snapshot.side not in ("BUY", "SELL") or snapshot.order_status not in _STATES:
        raise ValueError("Invalid side or order status")
    _integer(snapshot.revision, "revision")
    if snapshot.revision > _MAX_SEQ:
        raise ValueError("Revision overflow")
    _integer(snapshot.observed_ms, "snapshot time")
    for name in ("max_snapshot_age_ms", "max_receipt_lag_ms", "max_fills"):
        v = getattr(policy, name)
        if type(v) is not int or not 1 <= v <= (60_000 if name != "max_fills" else 10_000):
            raise ValueError(f"Invalid {name}")
    if not isinstance(snapshot.fills, tuple) or len(snapshot.fills) > policy.max_fills:
        raise ValueError("Invalid fill population")
    requested = _decimal(snapshot.requested_quantity, "requested quantity", positive=True)
    stop = _decimal(snapshot.protective_stop, "protective stop", positive=True)
    point = _decimal(snapshot.point_value_cash, "point value", positive=True)
    fee_cap = _decimal(policy.max_total_fee_cash, "fee cap")
    loss_cap = _decimal(policy.max_position_loss_cash, "position loss cap", positive=True)
    seen = set()
    parsed = []
    with localcontext() as ctx:
        ctx.prec = 90
        total_quantity = Decimal(0)
        total_fees = Decimal(0)
        stop_loss = Decimal(0)
        total_price_quantity = Decimal(0)
        latest_execution = -1
        for fill in snapshot.fills:
            if not isinstance(fill, FillReceipt):
                raise ValueError("Invalid fill receipt")
            _identity(fill.fill_id, "fill ID")
            if fill.fill_id in seen:
                raise ValueError("Duplicate fill ID")
            seen.add(fill.fill_id)
            qty = _decimal(fill.quantity, "fill quantity", positive=True)
            price = _decimal(fill.price, "fill price", positive=True)
            fee = _decimal(fill.fee_cash, "fill fee")
            _integer(fill.executed_ms, "fill execution time")
            _integer(fill.received_ms, "fill receipt time")
            if not 0 < fill.executed_ms <= fill.received_ms <= snapshot.observed_ms:
                raise ValueError("Future, reversed or zero fill timestamps")
            if fill.received_ms - fill.executed_ms > policy.max_receipt_lag_ms:
                raise ValueError("Excessive fill receipt latency")
            if fill.executed_ms < latest_execution:
                raise ValueError("Out-of-order execution timestamps")
            latest_execution = fill.executed_ms
            if (snapshot.side == "BUY" and stop >= price or
                    snapshot.side == "SELL" and stop <= price):
                raise ValueError("Protective stop invalid for executed fill")
            total_quantity += qty
            total_fees += fee
            total_price_quantity += qty * price
            stop_loss += qty * point * (price - stop if snapshot.side == "BUY" else stop - price)
            parsed.append((fill.fill_id, qty, price, fee, fill.executed_ms, fill.received_ms))
        if total_quantity > requested:
            raise ValueError("Cumulative fills exceed requested quantity")
        if total_quantity == 0 and snapshot.order_status in ("PARTIALLY_FILLED", "FILLED"):
            raise ValueError("Missing fill evidence")
        if snapshot.order_status == "OPEN" and total_quantity != 0:
            raise ValueError("Open order cannot have fills; use PARTIALLY_FILLED")
        if snapshot.order_status == "PARTIALLY_FILLED" and not 0 < total_quantity < requested:
            raise ValueError("Partial status inconsistent with fill quantity")
        if snapshot.order_status == "FILLED" and total_quantity != requested:
            raise ValueError("Filled status inconsistent with requested quantity")
        if snapshot.order_status == "REJECTED" and total_quantity != 0:
            raise ValueError("Rejected order cannot have fills")
        estimated_loss = stop_loss + total_fees
        return {
            "requested": requested, "filled": total_quantity, "fees": total_fees,
            "stop_loss": estimated_loss, "average": total_price_quantity / total_quantity if total_quantity else None,
            "fee_cap": fee_cap, "loss_cap": loss_cap, "parsed": parsed,
            "fresh": snapshot.observed_ms <= now_ms and now_ms - snapshot.observed_ms <= policy.max_snapshot_age_ms,
        }


def review_paper_fill_receipts(current: FillSnapshot, policy: FillReviewPolicy, *,
                               server_now_ms: int, previous: FillSnapshot | None = None) -> dict:
    """Review untrusted fill populations; NEVER grants execution or settlement.

    Previous must be an independently retained prior observation. A current
    snapshot supplied by the same untrusted caller cannot prove broker origin.
    """
    current_state = _validate(current, policy, server_now_ms)
    checks = {
        "current_snapshot_fresh": current_state["fresh"],
        "fee_cap": current_state["fees"] <= current_state["fee_cap"],
        "stressed_stop_loss_cap": current_state["stop_loss"] <= current_state["loss_cap"],
        "known_order_state": current.order_status != "UNKNOWN",
    }
    if previous is not None:
        prior_state = _validate(previous, policy, server_now_ms)
        stable = ("account_alias", "order_alias", "instrument", "provider", "venue",
                  "side", "requested_quantity", "protective_stop", "point_value_cash")
        checks["order_terms_immutable"] = all(getattr(previous, k) == getattr(current, k) for k in stable)
        checks["previous_snapshot_not_future"] = previous.observed_ms <= server_now_ms
        checks["revision_advances"] = current.revision > previous.revision
        checks["observation_advances"] = current.observed_ms > previous.observed_ms
        prior_by_id = {r[0]: r for r in prior_state["parsed"]}
        now_by_id = {r[0]: r for r in current_state["parsed"]}
        checks["prior_fills_immutable"] = all(now_by_id.get(fid) == value for fid, value in prior_by_id.items())
        checks["cumulative_quantity_nondecreasing"] = current_state["filled"] >= prior_state["filled"]
        checks["terminal_state_immutable"] = (previous.order_status not in _TERMINAL or
                                              current.order_status == previous.order_status)
        checks["no_state_regression"] = not (
            previous.order_status == "PARTIALLY_FILLED" and current.order_status == "OPEN")
        # New fill observations must not silently insert backdated executions.
        prior_latest = max((r[4] for r in prior_state["parsed"]), default=-1)
        checks["new_fills_not_backdated"] = all(r[4] >= prior_latest for fid, r in now_by_id.items()
                                                   if fid not in prior_by_id)
    with localcontext() as ctx:
        ctx.prec = 90
        # Canonicalize input decimals so harmless string formatting does not
        # change a fingerprint. Hash aliases rather than exposing identifiers.
        canonical = {
            "account_sha256": hashlib.sha256(current.account_alias.encode()).hexdigest(),
            "order_sha256": hashlib.sha256(current.order_alias.encode()).hexdigest(),
            "instrument": current.instrument, "provider": current.provider, "venue": current.venue,
            "side": current.side, "status": current.order_status, "revision": current.revision,
            "requested_quantity": str(current_state["requested"].normalize()),
            "protective_stop": str(_decimal(current.protective_stop, "stop").normalize()),
            "point_value_cash": str(_decimal(current.point_value_cash, "point value").normalize()),
            "observed_ms": current.observed_ms,
            "fills": [{"id_sha256": hashlib.sha256(r[0].encode()).hexdigest(),
                       "quantity": str(r[1].normalize()), "price": str(r[2].normalize()), "fee_cash": str(r[3].normalize()),
                       "executed_ms": r[4], "received_ms": r[5]} for r in current_state["parsed"]],
        }
        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "decision": "HOLD_RECONCILIATION",  # Never promote unverified data to execution/settlement
            "structural_checks_pass": all(checks.values()),
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "filled_quantity": str(current_state["filled"]),
            "remaining_quantity": str(current_state["requested"] - current_state["filled"]),
            "weighted_average_fill_price": str(current_state["average"]) if current_state["average"] is not None else None,
            "cumulative_fee_cash": str(current_state["fees"]),
            "illustrative_stop_loss_including_fees_cash": str(current_state["stop_loss"]),
            "receipt_population_sha256": fingerprint,
            "broker_receipts_authenticated": False,
            "broker_terminal_state_authenticated": False,
            "reservation_may_be_released": False,
            "paper_fill_recorded": False,
            "may_execute_paper_order": False,
            "may_execute_real_order": False,
            "warnings": [
                "Caller-supplied fill receipts and terminal states are not broker-authenticated.",
                "A protective stop is not a guaranteed fill price; gaps and costs can exceed this estimate.",
                "Do not release reservations or retry uncertain orders without independently authenticated reconciliation.",
            ],
        }
