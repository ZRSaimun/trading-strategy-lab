"""Disconnected PAPER portfolio concentration and correlated-shock preflight.

All values, quote timestamps, inventory completeness and group labels are caller
declarations, not broker attestations. This module has no I/O or execution path.
"""
from decimal import Decimal, localcontext
import hashlib
import json
import re

SCHEMA = "paper-portfolio-concentration-v1"
MAX_MS = 8_640_000_000_000_000
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
ROOT = {"account_alias", "provider", "currency", "equity_cash", "limits",
        "positions", "candidate", "inventory_observed_ms",
        "inventory_received_ms", "inventory_complete"}
LIMITS = {"max_position_stress_cash", "max_group_stress_cash",
          "max_portfolio_stress_cash", "max_symbol_notional_cash",
          "max_group_notional_cash", "max_gross_notional_cash",
          "max_margin_cash", "max_leverage", "group_shock_multiplier"}
POSITION = {"position_id", "instrument", "risk_group", "side",
            "gross_notional_cash", "stressed_loss_cash", "margin_cash",
            "quote_observed_ms", "quote_received_ms", "quote_id"}


def _object(value, fields, name):
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{name}: unexpected or missing fields")
    return value


def _id(value, name):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name}: invalid identifier")
    return value


def _cash(value, name):
    if type(value) is not str or not DECIMAL.fullmatch(value):
        raise ValueError(f"{name}: expected bounded nonnegative plain decimal string")
    return Decimal(value)


def _time(value, name):
    if type(value) is not int or not 0 <= value <= MAX_MS:
        raise ValueError(f"{name}: invalid epoch milliseconds")
    return value


def _snapshot_times(observed, received, now_ms):
    return (observed <= received <= now_ms,
            observed <= received <= now_ms and now_ms - observed <= 3000,
            observed <= received <= now_ms and received - observed <= 1000)


def _position(raw):
    p = _object(raw, POSITION, "position")
    result = {k: _id(p[k], k) for k in
              ("position_id", "instrument", "risk_group", "quote_id")}
    if p["side"] not in ("BUY", "SELL") or type(p["side"]) is not str:
        raise ValueError("position: invalid side")
    result["side"] = p["side"]
    for k in ("gross_notional_cash", "stressed_loss_cash", "margin_cash"):
        result[k] = _cash(p[k], k)
        if result[k] <= 0:
            raise ValueError(f"{k}: must be positive; unknown exposure is not zero")
    for k in ("quote_observed_ms", "quote_received_ms"):
        result[k] = _time(p[k], k)
    return result


def evaluate_portfolio_concentration(snapshot, *, now_ms):
    """Evaluate a declared portfolio; ALWAYS hold for broker reconciliation.

    Caller must supply a trusted server clock. Never interpret the output as
    broker inventory, an approval token, or permission to submit any order.
    """
    now_ms = _time(now_ms, "server now_ms")
    s = _object(snapshot, ROOT, "snapshot")
    account = _id(s["account_alias"], "account_alias")
    provider = _id(s["provider"], "provider")
    currency = s["currency"]
    if type(currency) is not str or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency: expected ISO uppercase currency code")
    equity = _cash(s["equity_cash"], "equity_cash")
    if equity <= 0:
        raise ValueError("equity_cash must be positive")
    limits_raw = _object(s["limits"], LIMITS, "limits")
    limits = {k: _cash(limits_raw[k], k) for k in LIMITS}
    if any(v <= 0 for v in limits.values()):
        raise ValueError("all limits must be positive")
    if not 1 <= limits["group_shock_multiplier"] <= 5:
        raise ValueError("group_shock_multiplier must be between 1 and 5")
    if limits["max_leverage"] > 5:
        raise ValueError("review-policy maximum leverage is 5x")
    if type(s["inventory_complete"]) is not bool:
        raise ValueError("inventory_complete must be boolean")
    inv_observed = _time(s["inventory_observed_ms"], "inventory_observed_ms")
    inv_received = _time(s["inventory_received_ms"], "inventory_received_ms")
    if type(s["positions"]) is not list or len(s["positions"]) > 50:
        raise ValueError("positions must be a list of at most 50")
    positions = [_position(p) for p in s["positions"]]
    candidate = _position(s["candidate"])
    ids = [p["position_id"] for p in positions]
    checks = {}
    checks["distinct_position_ids"] = (
        len(set(ids)) == len(ids) and candidate["position_id"] not in ids
    )
    checks["supported_public_api_account"] = provider in (
        "Trading212-Invest", "Trading212-StocksISA"
    )
    checks["inventory_declared_complete"] = s["inventory_complete"]
    inv_order, inv_fresh, inv_transport = _snapshot_times(
        inv_observed, inv_received, now_ms
    )
    checks["inventory_timestamp_order"] = inv_order
    checks["inventory_fresh"] = inv_fresh
    checks["inventory_transport_fresh"] = inv_transport
    checks["all_quotes_fresh"] = True
    checks["all_quote_timestamps_ordered"] = True
    checks["all_quote_transport_fresh"] = True
    for p in positions + [candidate]:
        ordered, fresh, transport = _snapshot_times(
            p["quote_observed_ms"], p["quote_received_ms"], now_ms
        )
        checks["all_quote_timestamps_ordered"] &= ordered
        checks["all_quotes_fresh"] &= fresh
        checks["all_quote_transport_fresh"] &= transport
    with localcontext() as ctx:
        ctx.prec = 60
        all_positions = positions + [candidate]
        multiplier = limits["group_shock_multiplier"]
        gross = sum((p["gross_notional_cash"] for p in all_positions), Decimal(0))
        margin = sum((p["margin_cash"] for p in all_positions), Decimal(0))
        base_loss = sum((p["stressed_loss_cash"] for p in all_positions), Decimal(0))
        shocked_loss = base_loss * multiplier
        group_gross = {}
        group_loss = {}
        symbol_gross = {}
        for p in all_positions:
            g, symbol = p["risk_group"], p["instrument"]
            group_gross[g] = group_gross.get(g, Decimal(0)) + p["gross_notional_cash"]
            group_loss[g] = group_loss.get(g, Decimal(0)) + p["stressed_loss_cash"]
            symbol_gross[symbol] = symbol_gross.get(symbol, Decimal(0)) + p["gross_notional_cash"]
        checks["position_stress_within_cap"] = (
            candidate["stressed_loss_cash"] * multiplier
            <= limits["max_position_stress_cash"]
        )
        checks["every_group_stress_within_cap"] = all(
            loss * multiplier <= limits["max_group_stress_cash"]
            for loss in group_loss.values()
        )
        checks["every_group_notional_within_cap"] = all(
            n <= limits["max_group_notional_cash"] for n in group_gross.values()
        )
        checks["every_symbol_notional_within_cap"] = all(
            n <= limits["max_symbol_notional_cash"] for n in symbol_gross.values()
        )
        checks["portfolio_stress_within_cap"] = (
            shocked_loss <= limits["max_portfolio_stress_cash"]
        )
        checks["gross_notional_within_cap"] = (
            gross <= limits["max_gross_notional_cash"]
        )
        checks["gross_leverage_within_cap"] = (
            gross <= equity * limits["max_leverage"]
        )
        checks["margin_within_cap_and_equity"] = (
            margin <= limits["max_margin_cash"] and margin <= equity
        )
        checks["post_stress_equity_covers_margin"] = (
            equity - shocked_loss > margin
        )
        checks["policy_caps_consistent"] = (
            limits["max_position_stress_cash"] <= limits["max_group_stress_cash"]
            <= limits["max_portfolio_stress_cash"] <= equity
            and limits["max_margin_cash"] <= equity
        )
        def plain(v):
            return format(v, "f")
        summary = {
            "gross_notional_cash": plain(gross),
            "reserved_margin_cash": plain(margin),
            "declared_base_stress_loss_cash": plain(base_loss),
            "correlated_shock_loss_cash": plain(shocked_loss),
            "post_shock_equity_cash": plain(equity - shocked_loss),
            "group_shock_loss_cash": {k: plain(group_loss[k] * multiplier)
                                      for k in sorted(group_loss)},
            "group_gross_notional_cash": {k: plain(group_gross[k])
                                          for k in sorted(group_gross)},
            "symbol_gross_notional_cash": {k: plain(symbol_gross[k])
                                           for k in sorted(symbol_gross)},
        }
    canonical = {
        "schema": SCHEMA, "account": account, "provider": provider,
        "currency": currency, "equity": str(equity),
        "limits": {k: str(limits[k]) for k in sorted(limits)},
        "positions": [{k: str(p[k]) if isinstance(p[k], Decimal) else p[k]
                       for k in sorted(p)} for p in positions],
        "candidate": {k: str(candidate[k]) if isinstance(candidate[k], Decimal)
                      else candidate[k] for k in sorted(candidate)},
        "inventory_observed_ms": inv_observed,
        "inventory_received_ms": inv_received,
        "inventory_complete": s["inventory_complete"], "now_ms": now_ms,
    }
    fingerprint = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")).hexdigest()
    return {
        "schema": SCHEMA, "status": "HOLD_RECONCILIATION",
        "checks": checks, "failed_checks": [k for k, ok in checks.items() if not ok],
        "assumption_checks_pass": all(checks.values()),
        "summary": summary, "review_sha256": fingerprint,
        "inventory_authenticated": False, "quotes_authenticated": False,
        "risk_groups_authenticated": False, "owner_approval_recorded": False,
        "may_execute_paper_order": False, "may_execute_real_order": False,
        "warnings": [
            "Caller-declared inventory, currency conversion, stress losses and risk groups are unauthenticated.",
            "Opposing positions never offset: correlated stress sums gross losses without hedge credit.",
            "The group multiplier is a scenario, not a bound on slippage, gaps or maximum losses.",
            "Fingerprint is diagnostic, not a signature, owner approval or execution authorization.",
            "Reconcile broker positions, fills, protective stops and durable reservations before any use.",
        ],
    }
