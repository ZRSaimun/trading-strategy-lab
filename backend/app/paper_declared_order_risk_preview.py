"""Disconnected order-risk preview. Never sends, reserves or authorizes orders.

All inputs are caller-declared; matching limits are NOT trusted broker evidence.
A production risk gate must recheck atomically against authenticated positions,
quotes, margin and order history immediately before each approved submission.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import re
from typing import Any

_MAX_MS = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DEC = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")
_SIGNED = re.compile(r"-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")
_ORDER = {"client_order_id", "intent_sha", "instrument", "side", "quantity", "stop_price", "requested_leverage"}
_QUOTE = {"instrument", "source", "bid", "ask", "observed_at_ms", "received_at_ms"}
_ACCOUNT = {"broker", "account_alias", "equity", "free_margin", "daily_realized_pnl", "open_notional", "open_risk", "circuit_breaker_open"}
_POLICY = {"max_quote_age_ms", "max_transport_lag_ms", "max_spread_bps", "max_slippage_bps", "max_leverage", "max_position_loss_pct", "max_total_open_risk_pct", "max_daily_loss_pct", "max_notional_pct", "max_order_quantity", "max_orders_per_window", "order_window_ms"}
_RECENT = {"client_order_id", "intent_sha", "submitted_at_ms"}
_BROKERS = {"PAPER-LOCAL", "T212-INVEST-DEMO", "T212-STOCKSISA-DEMO", "T212-INVEST-LIVE", "T212-STOCKSISA-LIVE"}


def _obj(value: Any, fields: set[str], name: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"Invalid {name} fields")
    return value


def _id(value: Any, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _sha(value: Any) -> str:
    if type(value) is not str or not _SHA.fullmatch(value) or value == "0" * 64:
        raise ValueError("Invalid order intent digest")
    return value


def _num(value: Any, name: str, *, signed: bool = False, positive: bool = False) -> Decimal:
    if type(value) is not str or not (_SIGNED if signed else _DEC).fullmatch(value):
        raise ValueError(f"Invalid {name}")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {name}") from exc
    if positive and result <= 0:
        raise ValueError(f"Invalid {name}")
    return result


def _ms(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"Invalid {name}")
    return value


def inspect_declared_order_risk_preview(order: dict, quote: dict, account: dict,
                                        policy: dict, recent_orders: list[dict],
                                        now_ms: int) -> dict[str, Any]:
    """Fail-closed offline arithmetic; output is *never* order authorization."""
    o = _obj(order, _ORDER, "order")
    q = _obj(quote, _QUOTE, "quote")
    a = _obj(account, _ACCOUNT, "account")
    p = _obj(policy, _POLICY, "policy")
    now = _ms(now_ms, "check time")
    cid = _id(o["client_order_id"], "client order ID")
    intent = _sha(o["intent_sha"])
    instrument = _id(o["instrument"], "instrument")
    if type(o["side"]) is not str or o["side"] not in ("BUY", "SELL"):
        raise ValueError("Invalid side")
    quantity = _num(o["quantity"], "quantity", positive=True)
    stop = _num(o["stop_price"], "stop price", positive=True)
    leverage = _num(o["requested_leverage"], "requested leverage", positive=True)
    _id(q["instrument"], "quote instrument")
    _id(q["source"], "quote source")
    bid = _num(q["bid"], "bid", positive=True)
    ask = _num(q["ask"], "ask", positive=True)
    observed = _ms(q["observed_at_ms"], "quote observation")
    received = _ms(q["received_at_ms"], "quote receipt")
    broker = _id(a["broker"], "broker")
    _id(a["account_alias"], "account alias")
    if broker not in _BROKERS:
        raise ValueError("Unsupported broker label (no CFD support inferred)")
    if type(a["circuit_breaker_open"]) is not bool:
        raise ValueError("Invalid circuit breaker")
    equity = _num(a["equity"], "equity", positive=True)
    free_margin = _num(a["free_margin"], "free margin")
    pnl = _num(a["daily_realized_pnl"], "daily P&L", signed=True)
    open_notional = _num(a["open_notional"], "open notional")
    open_risk = _num(a["open_risk"], "open risk")
    limits = {key: _num(p[key], key, positive=True) for key in _POLICY if key not in
              {"max_quote_age_ms", "max_transport_lag_ms", "max_orders_per_window", "order_window_ms"}}
    for key in ("max_quote_age_ms", "max_transport_lag_ms", "order_window_ms"):
        if type(p[key]) is not int or not 1 <= p[key] <= 60_000:
            raise ValueError(f"Invalid {key}")
    if type(p["max_orders_per_window"]) is not int or not 1 <= p["max_orders_per_window"] <= 100:
        raise ValueError("Invalid max_orders_per_window")
    if (limits["max_spread_bps"] > 10_000 or limits["max_slippage_bps"] > 10_000
            or any(limits[k] > 100 for k in ("max_position_loss_pct", "max_total_open_risk_pct", "max_daily_loss_pct"))
            or limits["max_leverage"] > 100 or limits["max_notional_pct"] > 10_000):
        raise ValueError("Unsafe policy bounds")
    if type(recent_orders) is not list or len(recent_orders) > 10_000:
        raise ValueError("Invalid recent order history")
    failures: set[str] = set()
    if a["circuit_breaker_open"]:
        failures.add("circuit_breaker_open")
    if q["instrument"] != instrument:
        failures.add("quote_instrument_mismatch")
    if ask <= bid:
        failures.add("invalid_quote_market")
    if not observed <= received <= now or now - observed > p["max_quote_age_ms"]:
        failures.add("stale_or_future_quote")
    if not observed <= received <= now or received - observed > p["max_transport_lag_ms"]:
        failures.add("quote_transport_lag")
    if (ask - bid) / ask * 10_000 > limits["max_spread_bps"]:
        failures.add("spread_limit")
    entry = ask if o["side"] == "BUY" else bid
    if (o["side"] == "BUY" and stop >= bid) or (o["side"] == "SELL" and stop <= ask):
        failures.add("invalid_protective_stop")
    # Decimal default precision (28) can round large notional products near a limit.
    with localcontext() as ctx:
        ctx.prec = 80
        notional = entry * quantity
        # Conservative declared gap-to-stop + explicit slippage buffer. A stop is
        # NOT a guaranteed loss cap during gaps, outages or failed broker execution.
        risk = abs(entry - stop) * quantity + notional * limits["max_slippage_bps"] / 10_000
        margin = notional / leverage
        if leverage > limits["max_leverage"]:
            failures.add("leverage_limit")
        if quantity > limits["max_order_quantity"]:
            failures.add("quantity_limit")
        if margin > free_margin:
            failures.add("insufficient_declared_margin")
        if notional + open_notional > equity * limits["max_notional_pct"] / 100:
            failures.add("gross_exposure_limit")
        if risk > equity * limits["max_position_loss_pct"] / 100:
            failures.add("position_loss_limit")
        if risk + open_risk > equity * limits["max_total_open_risk_pct"] / 100:
            failures.add("portfolio_risk_limit")
        if max(Decimal(0), -pnl) + risk > equity * limits["max_daily_loss_pct"] / 100:
            failures.add("daily_loss_circuit_breaker")
    recent_in_window = 0
    seen_ids: set[str] = set()
    seen_intents: set[str] = set()
    for row in recent_orders:
        item = _obj(row, _RECENT, "recent order")
        prior_id = _id(item["client_order_id"], "recent order ID")
        prior_intent = _sha(item["intent_sha"])
        stamp = _ms(item["submitted_at_ms"], "recent order time")
        if stamp > now:
            failures.add("future_order_history")
        if prior_id in seen_ids or prior_intent in seen_intents:
            failures.add("duplicate_order_history")
        seen_ids.add(prior_id)
        seen_intents.add(prior_intent)
        if prior_id == cid or prior_intent == intent:
            failures.add("duplicate_order_intent")
        if 0 <= now - stamp <= p["order_window_ms"]:
            recent_in_window += 1
    if recent_in_window >= p["max_orders_per_window"]:
        failures.add("order_rate_limit")
    return {
        "status": "HOLD_RISK_REVIEW" if failures else "DECLARED_RISK_PREVIEW_UNVERIFIED",
        "failed_checks": sorted(failures),
        "estimated_entry_price": str(entry),
        "declared_notional": str(notional),
        "declared_margin_required": str(margin),
        "estimated_stop_loss_with_slippage": str(risk),
        "broker_authenticated": False,
        "quote_authenticated": False,
        "stop_guaranteed": False,
        "atomic_reservation_verified": False,
        "requires_individual_owner_approval": True,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
