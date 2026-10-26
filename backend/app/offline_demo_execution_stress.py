"""Adverse-only sensitivity census for disconnected demo quote-tape simulations.

This is a deterministic stress *thought experiment* over caller-declared data.
No network, broker adapter, credentials, historical source authentication,
order submission, exit modelling, CFD financing, or profitability claim.
"""
from __future__ import annotations

import re
from decimal import Decimal, localcontext

from app.offline_demo_quote_tape_simulator import (
    _decimal, _digest, fingerprint_demo_quote_tape,
    simulate_declared_demo_quote_tape,
)

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}\Z")
_SPREAD = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,7})?\Z")
_FIELDS = frozenset({
    "name", "spread_widen_price", "extra_adverse_slippage_price",
    "depth_percent", "quote_delivery_delay_ms",
})
_MAX_STRESSES = 8


def _validate_stresses(stresses):
    if type(stresses) is not list or not 1 <= len(stresses) <= _MAX_STRESSES:
        raise ValueError("Require 1..8 declared adverse stress scenarios")
    names = set()
    for item in stresses:
        if type(item) is not dict or set(item) != _FIELDS:
            raise ValueError("Invalid exact adverse stress schema")
        name = item["name"]
        if (type(name) is not str or not _NAME.fullmatch(name)
                or name.lower() == "baseline" or name in names):
            raise ValueError("Duplicate or invalid stress name")
        names.add(name)
        spread = item["spread_widen_price"]
        if type(spread) is not str or not _SPREAD.fullmatch(spread):
            raise ValueError("Spread widening must be a bounded exact decimal with <=7 places")
        slippage = _decimal(item["extra_adverse_slippage_price"], "extra slippage")
        if slippage > 1000 or Decimal(spread) > 1000:
            raise ValueError("Unbounded adverse price assumption")
        depth = item["depth_percent"]
        delay = item["quote_delivery_delay_ms"]
        if (type(depth) is not int or not 0 <= depth <= 100
                or type(delay) is not int or not 0 <= delay <= 60000):
            raise ValueError("Invalid bounded depth or delivery delay")
        if not (Decimal(spread) > 0 or slippage > 0 or depth < 100 or delay > 0):
            raise ValueError("Stress must actually worsen at least one assumption")
    return sorted(stresses, key=lambda s: s["name"])


def _summary(result):
    return {
        "status": result["status"],
        "hypothetical_filled_contracts": result["hypothetical_filled_contracts"],
        "remaining_contracts": result["remaining_contracts"],
        "hypothetical_fills": result["fills"],
        "spread_cost_cash": result["spread_cost_cash"],
        "adverse_slippage_cash": result["adverse_slippage_cash"],
        "commission_cash": result["commission_cash"],
        "total_entry_cost_cash": result["total_entry_cost_cash"],
        "quote_tape_sha256": result["quote_tape_sha256"],
        "scenario_sha256": result["scenario_sha256"],
    }


def _stressed_tape(scope, quotes, stress):
    """Transform *copies* only; never relabel transformed quotes as authentic."""
    delay = stress["quote_delivery_delay_ms"]
    depth = stress["depth_percent"]
    half_widen = Decimal(stress["spread_widen_price"]) / 2
    transformed = []
    with localcontext() as ctx:
        ctx.prec = 60
        for quote in quotes:
            received = quote["received_at_ms"] + delay
            if received > scope["as_of_ms"]:
                # Not yet delivered at the fixed as-of time; NOT a proof of no fill.
                continue
            bid = Decimal(quote["bid"]) - half_widen
            ask = Decimal(quote["ask"]) + half_widen
            if bid <= 0:
                raise ValueError("Spread stress would produce a nonpositive bid")
            changed = dict(quote)
            changed["bid"] = format(bid, "f")
            changed["ask"] = format(ask, "f")
            changed["received_at_ms"] = received
            changed["available_contracts"] = quote["available_contracts"] * depth // 100
            transformed.append(changed)
    return transformed


def audit_declared_demo_execution_stress(
    scope, intent, quotes, expected_quote_tape_sha256, stresses,
):
    """Rerun a complete declared adverse-only execution matrix.

    Baseline identity is checked by the upstream simulator before any scenario.
    Every stressed quote tape has its own fingerprint. Missing/late quotes are
    unknown, not evidence that a broker order had zero exposure. Total cost
    cannot be compared across scenarios with different filled quantities.
    """
    ordered = _validate_stresses(stresses)
    baseline = simulate_declared_demo_quote_tape(
        scope, intent, quotes, expected_quote_tape_sha256,
    )
    results = []
    for stress in ordered:
        stressed_scope = dict(scope)
        with localcontext() as ctx:
            ctx.prec = 60
            stressed_scope["adverse_slippage_price"] = format(
                Decimal(scope["adverse_slippage_price"])
                + Decimal(stress["extra_adverse_slippage_price"]), "f",
            )
        stressed_quotes = _stressed_tape(scope, quotes, stress)
        tape_sha = fingerprint_demo_quote_tape(stressed_scope, stressed_quotes)
        outcome = simulate_declared_demo_quote_tape(
            stressed_scope, intent, stressed_quotes, tape_sha,
        )
        results.append({
            "name": stress["name"],
            "assumptions": dict(stress),
            "derived_quote_count": len(stressed_quotes),
            "derived_only_not_authentic_quotes": True,
            **_summary(outcome),
        })

    requested = intent["requested_contracts"]
    every_full = all(
        x["hypothetical_filled_contracts"] == requested
        for x in [_summary(baseline), *results]
    )
    # Aggregate entry cash is only comparable when the filled quantities match.
    worst_comparable = (
        str(max(Decimal(x["total_entry_cost_cash"])
                for x in [_summary(baseline), *results]))
        if every_full else None
    )
    return {
        "protocol": "declared-demo-adverse-execution-stress-v1",
        "status": "HYPOTHETICAL_ADVERSE_SENSITIVITY_ONLY",
        "source_identity": {key: scope[key] for key in
                            ("provider", "venue", "account_alias", "instrument")},
        "as_of_ms": scope["as_of_ms"],
        "requested_contracts": requested,
        "baseline": _summary(baseline),
        "stresses": results,
        "stress_plan_sha256": _digest({
            "protocol": "declared-demo-adverse-execution-stress-v1",
            "baseline_scenario_sha256": baseline["scenario_sha256"],
            "stresses": ordered,
        }),
        "minimum_hypothetical_filled_contracts": min(
            [baseline["hypothetical_filled_contracts"]]
            + [x["hypothetical_filled_contracts"] for x in results]
        ),
        "all_scenarios_fully_filled": every_full,
        "worst_comparable_full_fill_entry_cost_cash": worst_comparable,
        "authenticated_market_data": False,
        "independent_liquidity_evidence": False,
        "models_exits_or_cfd_financing": False,
        "verified_profitability": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": (
            "Caller-declared quotes, depth and adverse stresses are not executable "
            "broker evidence. Fewer fills can lower total cash costs while "
            "increasing unfilled quantity. No exit, financing, overnight margin, "
            "queue priority, FX settlement, profitability or permission to trade."
        ),
    }
