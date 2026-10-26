"""Offline, fail-closed paper/broker snapshot reconciliation; never executes orders.

All inputs are UNAUTHENTICATED observations. The caller must supply a trusted
server clock and an externally persisted previous snapshot marker. No broker
connection, account approval, stop order, journal write or risk reservation.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
import re
from typing import Any


MAX_MS = 8_640_000_000_000_000
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}\Z")
BROKERS = {"Trading212-Invest", "Trading212-StocksISA", "Trading212-CFD"}


def _object(value: Any, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"Invalid {label} fields")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not ID.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_MS:
        raise ValueError(f"Invalid {label}")
    return value


def _money(value: Any, label: str, *, positive: bool = False) -> Decimal:
    # Strings only: reject float imprecision, booleans, NaN/Infinity and huge exponents.
    if type(value) is not str or not re.fullmatch(r"-?(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?", value):
        raise ValueError(f"Invalid {label}")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not amount.is_finite() or (positive and amount <= 0):
        raise ValueError(f"Invalid {label}")
    return amount


def _positions(items: Any, label: str, *, planned: bool) -> dict[str, dict]:
    if type(items) is not list or len(items) > 100:
        raise ValueError(f"Invalid {label}")
    out: dict[str, dict] = {}
    fields = {"instrument", "side", "quantity"}
    if planned:
        fields |= {"entry", "stop", "stress_exit", "point_value"}
    for item in items:
        row = _object(item, fields, label)
        symbol = _text(row["instrument"], "instrument")
        if symbol in out or row["side"] not in ("LONG", "SHORT"):
            raise ValueError("Duplicate instrument or invalid side")
        result = {"side": row["side"], "quantity": _money(row["quantity"], "quantity", positive=True)}
        if planned:
            for key in ("entry", "stop", "stress_exit", "point_value"):
                result[key] = _money(row[key], key, positive=True)
            if row["side"] == "LONG" and not (result["stress_exit"] < result["stop"] < result["entry"]):
                raise ValueError("Invalid long protective stop/stress direction")
            if row["side"] == "SHORT" and not (result["entry"] < result["stop"] < result["stress_exit"]):
                raise ValueError("Invalid short protective stop/stress direction")
        out[symbol] = result
    return out


def _quotes(items: Any) -> dict[str, dict]:
    if type(items) is not list or len(items) > 100:
        raise ValueError("Invalid quotes")
    out = {}
    for item in items:
        row = _object(item, {"instrument", "provider", "venue", "quote_id", "bid", "ask", "observed_at_ms", "received_at_ms"}, "quote")
        symbol = _text(row["instrument"], "quote instrument")
        if symbol in out:
            raise ValueError("Duplicate quote instrument")
        out[symbol] = {
            "provider": _text(row["provider"], "provider"),
            "venue": _text(row["venue"], "venue"),
            "quote_id": _text(row["quote_id"], "quote ID"),
            "bid": _money(row["bid"], "bid", positive=True),
            "ask": _money(row["ask"], "ask", positive=True),
            "observed_at_ms": _integer(row["observed_at_ms"], "quote time"),
            "received_at_ms": _integer(row["received_at_ms"], "quote receipt"),
        }
    return out


def evaluate_snapshot(expected: dict, observed: dict, now_ms: int) -> dict:
    """Compare a snapshot with high-precision Decimal arithmetic, without side effects."""
    with localcontext() as context:
        context.prec = 100
        return _evaluate_snapshot(expected, observed, now_ms)


def _evaluate_snapshot(expected: dict, observed: dict, now_ms: int) -> dict:
    """Compare one untrusted observation to owner-declared paper ledger state.

    Does not mutate state or imply broker authentication. A clean comparison
    is only a candidate for *manual* reconciliation, never order permission.
    """
    now_ms = _integer(now_ms, "trusted server time")
    e = _object(expected, {
        "broker", "account_alias", "provider", "venue", "positions", "max_quote_age_ms",
        "max_transport_lag_ms", "max_spread_bps", "max_position_loss_cash",
        "max_daily_loss_cash", "max_gross_leverage", "max_margin_fraction",
        "previous_snapshot_id", "previous_sequence", "previous_observed_at_ms",
        "circuit_latched",
    }, "expected policy")
    o = _object(observed, {
        "broker", "account_alias", "snapshot_id", "sequence", "observed_at_ms",
        "received_at_ms", "equity", "used_margin", "daily_realized_pnl",
        "positions", "quotes",
    }, "observed snapshot")
    broker = _text(e["broker"], "broker")
    if broker not in BROKERS:
        raise ValueError("Unsupported broker")
    account = _text(e["account_alias"], "account alias")
    provider = _text(e["provider"], "provider")
    venue = _text(e["venue"], "venue")
    sid = _text(o["snapshot_id"], "snapshot ID")
    prior_sid = e["previous_snapshot_id"]
    if prior_sid is not None:
        _text(prior_sid, "previous snapshot ID")
    prior_sequence = _integer(e["previous_sequence"], "previous sequence")
    prior_time = _integer(e["previous_observed_at_ms"], "previous time")
    sequence = _integer(o["sequence"], "sequence")
    observed_ms = _integer(o["observed_at_ms"], "snapshot time")
    received_ms = _integer(o["received_at_ms"], "snapshot receipt")
    max_age = _integer(e["max_quote_age_ms"], "maximum quote age")
    max_lag = _integer(e["max_transport_lag_ms"], "maximum transport lag")
    if not 100 <= max_age <= 60000 or max_lag > 60000:
        raise ValueError("Unsafe freshness policy")
    max_spread = _money(e["max_spread_bps"], "maximum spread", positive=True)
    max_position_loss = _money(e["max_position_loss_cash"], "position cap", positive=True)
    max_daily_loss = _money(e["max_daily_loss_cash"], "daily cap", positive=True)
    max_leverage = _money(e["max_gross_leverage"], "leverage cap", positive=True)
    max_margin = _money(e["max_margin_fraction"], "margin fraction", positive=True)
    if max_margin > 1 or max_spread > 10000 or max_leverage > 100:
        raise ValueError("Unsafe limit policy")
    if type(e["circuit_latched"]) is not bool:
        raise ValueError("Invalid circuit latch")
    equity = _money(o["equity"], "equity", positive=True)
    used_margin = _money(o["used_margin"], "used margin")
    realized = _money(o["daily_realized_pnl"], "daily realized P&L")
    if used_margin < 0:
        raise ValueError("Negative used margin")
    planned = _positions(e["positions"], "planned positions", planned=True)
    actual = _positions(o["positions"], "observed positions", planned=False)
    quotes = _quotes(o["quotes"])
    checks: dict[str, bool] = {
        "account_identity": o["broker"] == broker and o["account_alias"] == account,
        "documented_account_api_scope": broker != "Trading212-CFD",
        "snapshot_monotonic": (sid != prior_sid and sequence > prior_sequence and observed_ms > prior_time),
        "snapshot_fresh": (observed_ms <= received_ms <= now_ms and now_ms - observed_ms <= max_age
                           and received_ms - observed_ms <= max_lag),
        "positions_exactly_match": (set(actual) == set(planned) and all(
            actual[s]["side"] == p["side"] and actual[s]["quantity"] == p["quantity"]
            for s, p in planned.items() if s in actual)),
        "quotes_exactly_match": set(quotes) == set(planned),
        "circuit_not_latched": not e["circuit_latched"],
        "margin_within_cap": used_margin <= equity * max_margin,
        "daily_realized_within_cap": realized > -max_daily_loss,
    }
    gross_notional = Decimal(0)
    total_stress_loss = Decimal(0)
    mark_downside = Decimal(0)
    for symbol, p in planned.items():
        q = quotes.get(symbol)
        if q is None:
            checks[f"quote_present:{symbol}"] = False
            continue
        prefix = f"{symbol}:"
        checks[prefix + "source_identity"] = q["provider"] == provider and q["venue"] == venue
        checks[prefix + "quote_order"] = q["ask"] > q["bid"]
        spread_bps = ((q["ask"] / q["bid"]) - 1) * 10000
        checks[prefix + "spread"] = checks[prefix + "quote_order"] and spread_bps <= max_spread
        checks[prefix + "quote_fresh"] = (
            q["observed_at_ms"] <= q["received_at_ms"] <= now_ms
            and now_ms - q["observed_at_ms"] <= max_age
            and q["received_at_ms"] - q["observed_at_ms"] <= max_lag
            and q["observed_at_ms"] <= observed_ms
        )
        # A snapshot cannot contain a quote received after the snapshot was
        # received. A quote older than the prior persisted snapshot is not
        # fresh evidence merely because a new snapshot ID was supplied.
        checks[prefix + "quote_snapshot_causal"] = (
            q["received_at_ms"] <= received_ms
            and q["observed_at_ms"] > prior_time
        )
        mark = q["bid"] if p["side"] == "LONG" else q["ask"]
        checks[prefix + "stop_not_breached"] = mark > p["stop"] if p["side"] == "LONG" else mark < p["stop"]
        # A breached stop is NOT evidence of a stop fill. When the current
        # executable side has gapped past the declared stress exit, retain the
        # worse price in the loss estimate (for BOTH long and short positions).
        worst_exit = (min(p["stress_exit"], mark) if p["side"] == "LONG"
                      else max(p["stress_exit"], mark))
        adverse_distance = (p["entry"] - worst_exit if p["side"] == "LONG"
                            else worst_exit - p["entry"])
        stress_loss = max(Decimal(0), adverse_distance) * p["quantity"] * p["point_value"]
        checks[prefix + "position_loss_cap"] = stress_loss <= max_position_loss
        total_stress_loss += stress_loss
        # A lower current ask must not erase the notional committed at entry.
        # This is a conservative scenario, not verified broker margin.
        gross_notional += max(p["entry"], q["ask"]) * p["quantity"] * p["point_value"]
        unrealized = ((mark - p["entry"]) if p["side"] == "LONG" else (p["entry"] - mark)) * p["quantity"] * p["point_value"]
        mark_downside += min(unrealized, Decimal(0))
        if broker != "Trading212-CFD":
            checks[prefix + "cash_account_long_only"] = p["side"] == "LONG"
    checks["portfolio_gross_leverage"] = gross_notional <= equity * max_leverage
    checks["projected_daily_downside"] = realized + mark_downside - total_stress_loss > -max_daily_loss
    if broker != "Trading212-CFD":
        checks["cash_account_notional_within_equity_assumption"] = gross_notional <= equity
    passed = all(checks.values())
    # Fingerprint is for diagnostic correlation only; it is NOT a signature.
    diagnostic = json.dumps({"account": account, "snapshot": sid, "sequence": sequence,
                             "observed": observed_ms, "failed": sorted(k for k, v in checks.items() if not v)},
                            sort_keys=True, separators=(",", ":"))
    return {
        "status": "CONSISTENT_UNVERIFIED" if passed else "HOLD_RECONCILIATION",
        "checks": checks,
        "failed_checks": sorted(k for k, v in checks.items() if not v),
        "gross_notional_cash": str(gross_notional),
        "stress_loss_cash": str(total_stress_loss),
        "marked_downside_cash": str(mark_downside),
        "diagnostic_sha256": sha256(diagnostic.encode()).hexdigest(),
        "broker_authenticated": False,
        "protective_stop_broker_verified": False,
        "journal_committed": False,
        "risk_reserved": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warnings": [
            "Untrusted input: a consistent snapshot is not authenticated broker evidence.",
            "Stop observations do not place stops or imply a fill at the stop; gaps can exceed stressed estimates.",
            "External durable sequence tracking, transactional journal reconciliation and independent account authentication are required.",
        ],
    }
