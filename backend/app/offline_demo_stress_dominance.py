"""Fail-closed adverse-execution dominance census over caller-declared demo quotes.

This is a disconnected invariant check, NOT a broker adapter, execution gate,
source authentication, realistic fill guarantee, or profitability estimate.
"""
from __future__ import annotations

from decimal import Decimal

from app import offline_demo_execution_stress as engine
from app.offline_demo_quote_tape_simulator import _digest


def _check_fill_accounting(outcome, requested, original_quotes, side, slip, as_of):
    """Reconcile a reported hypothetical scenario to the original quote lineage."""
    filled = outcome["hypothetical_filled_contracts"]
    remaining = outcome["remaining_contracts"]
    if (type(filled) is not int or type(remaining) is not int
            or filled < 0 or remaining < 0 or filled + remaining != requested):
        raise ValueError("Invalid hypothetical fill quantity accounting")
    fills = outcome["hypothetical_fills"]
    if type(fills) is not list or len(fills) > len(original_quotes):
        raise ValueError("Invalid hypothetical fill population")
    total = 0
    used = set()
    for fill in fills:
        qid = fill["quote_id"]
        if qid in used or qid not in original_quotes:
            raise ValueError("Unknown or repeated quote identity in hypothetical fills")
        used.add(qid)
        original = original_quotes[qid]
        qty = fill["contracts"]
        if type(qty) is not int or not 1 <= qty <= original["available_contracts"]:
            raise ValueError("Hypothetical fill exceeds original declared depth")
        at = fill["at_ms"]
        if (type(at) is not int or at < original["received_at_ms"]
                or at > as_of):
            raise ValueError("Stress introduced an earlier or future quote receipt")
        reference = (Decimal(original["ask"]) + slip if side == "BUY"
                     else Decimal(original["bid"]) - slip)
        price = Decimal(fill["price"])
        if not price.is_finite() or price <= 0 or (
            (side == "BUY" and price < reference) or
            (side == "SELL" and price > reference)
        ):
            raise ValueError("Adverse stress improved original executable-side price")
        total += qty
    if total != filled:
        raise ValueError("Hypothetical fills disagree with filled quantity")
    costs = [Decimal(outcome[k]) for k in (
        "spread_cost_cash", "adverse_slippage_cash", "commission_cash",
    )]
    total_cost = Decimal(outcome["total_entry_cost_cash"])
    if (not all(x.is_finite() and x >= 0 for x in costs)
            or not total_cost.is_finite() or sum(costs) != total_cost):
        raise ValueError("Invalid hypothetical cash cost decomposition")


def audit_declared_demo_stress_dominance(
    scope, intent, quotes, expected_quote_tape_sha256, stresses,
):
    """Recompute and audit adverse-only stress outcomes, never permit an order.

    All stresses must have no more hypothetical fills than the baseline and
    may not improve the original executable-side quote price or receipt time.
    When fills differ, aggregate cash costs are *not* comparable. Every input
    and quote remains caller-declared; this does not prove source completeness.
    """
    report = engine.audit_declared_demo_execution_stress(
        scope, intent, quotes, expected_quote_tape_sha256, stresses,
    )
    originals = {quote["quote_id"]: quote for quote in quotes}
    requested = intent["requested_contracts"]
    expected_identity = {key: scope[key] for key in
                         ("provider", "venue", "account_alias", "instrument")}
    if (report["source_identity"] != expected_identity
            or report["as_of_ms"] != scope["as_of_ms"]
            or report["requested_contracts"] != requested
            or len(report["stresses"]) != len(stresses)):
        raise ValueError("Stress report changed source, cutoff or scenario population")
    slip = Decimal(scope["adverse_slippage_price"])
    baseline = report["baseline"]
    if baseline["quote_tape_sha256"] != expected_quote_tape_sha256:
        raise ValueError("Stress report changed baseline quote fingerprint")
    _check_fill_accounting(baseline, requested, originals, intent["side"],
                           slip, scope["as_of_ms"])
    baseline_filled = baseline["hypothetical_filled_contracts"]
    outcomes = [("baseline", baseline)]
    for stressed in report["stresses"]:
        _check_fill_accounting(stressed, requested, originals, intent["side"],
                               slip, scope["as_of_ms"])
        if stressed["hypothetical_filled_contracts"] > baseline_filled:
            raise ValueError("Adverse-only stress increased hypothetical fill quantity")
        if stressed["derived_quote_count"] > len(quotes):
            raise ValueError("Adverse stress fabricated extra quote population")
        outcomes.append((stressed["name"], stressed))
    minimum = min(row["hypothetical_filled_contracts"] for _, row in outcomes)
    if (report["minimum_hypothetical_filled_contracts"] != minimum
            or report["all_scenarios_fully_filled"] != (minimum == requested)):
        raise ValueError("Inconsistent adverse-stress summary")
    if minimum < requested and report["worst_comparable_full_fill_entry_cost_cash"] is not None:
        raise ValueError("Partial fills cannot establish comparable aggregate costs")
    if minimum == requested:
        maximum_cost = max(Decimal(row["total_entry_cost_cash"])
                           for _, row in outcomes)
        if Decimal(report["worst_comparable_full_fill_entry_cost_cash"]) != maximum_cost:
            raise ValueError("Incorrect comparable full-fill cost envelope")
    worst = [name for name, row in outcomes
             if row["hypothetical_filled_contracts"] == minimum]
    return {
        "protocol": "declared-demo-adverse-dominance-v1",
        "status": "SELF_DECLARED_DOMINANCE_CHECK_ONLY",
        "source_identity": report["source_identity"],
        "as_of_ms": report["as_of_ms"],
        "requested_contracts": requested,
        "baseline_hypothetical_filled_contracts": baseline_filled,
        "minimum_hypothetical_filled_contracts": minimum,
        "maximum_unfilled_contracts": requested - minimum,
        "minimum_fill_fraction": f"{minimum}/{requested}",
        "worst_fill_scenarios": worst,
        "all_scenarios_fully_filled": minimum == requested,
        "worst_comparable_full_fill_entry_cost_cash": (
            report["worst_comparable_full_fill_entry_cost_cash"]
            if minimum == requested else None
        ),
        "stress_plan_sha256": report["stress_plan_sha256"],
        "self_declared_report_sha256": _digest(report),
        "quote_lineage_and_cash_invariants_checked": True,
        "independently_authenticated_quotes": False,
        "actual_liquidity_verified": False,
        "realized_costs_or_financing_verified": False,
        "verified_profitability": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": (
            "Caller-declared quote and depth records cannot prove executable broker "
            "prices, complete quote populations, queue priority, actual fills, "
            "exits, CFD financing, FX settlement, or profitable strategy returns. "
            "No execution permission is conferred."
        ),
    }
