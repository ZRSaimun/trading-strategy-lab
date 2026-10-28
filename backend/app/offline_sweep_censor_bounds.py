"""Disconnected conditional bounds for unknown CRT/ICT trade exits.

This is a sensitivity calculation, not an outcome imputer, confidence interval,
trade selector, or permission to execute an order. Source clocks remain unauthenticated.
"""
from datetime import datetime
from decimal import Decimal as D, localcontext

from .offline_sweep_censor_aware_blocks import COST_BPS, COHORTS, EnteredTrade


def audit_censored_exit_bounds(trades, *, missing_gross_lower=D("-1"),
                               missing_gross_upper=D("1")):
    """Bound full-entered mean net R *conditional on caller-chosen exit bounds*.

    Illustrative extra round-trip bps are charged to all declared entered
    positions, including unknown exits. Actual exit costs and stop fills are
    unverified; a -1R stop is NOT a proven loss floor for gapping markets.
    """
    if type(trades) not in (list, tuple) or len(trades) > 10000:
        raise ValueError("Expected at most 10000 declared entered positions")
    if (type(missing_gross_lower) is not D or
            type(missing_gross_upper) is not D or
            not missing_gross_lower.is_finite() or
            not missing_gross_upper.is_finite() or
            missing_gross_lower > missing_gross_upper or
            any(abs(v.adjusted()) > 6 for v in
                (missing_gross_lower, missing_gross_upper))):
        raise ValueError("Finite ordered bounded missing-outcome assumptions required")
    by_cohort = {name: [] for name in COHORTS}
    previous = None
    for t in trades:
        if (not isinstance(t, EnteredTrade) or type(t.time) is not datetime or
                t.time.tzinfo is not None or t.cohort not in COHORTS or
                type(t.entry) is not D or type(t.risk) is not D or
                not t.entry.is_finite() or not t.risk.is_finite() or
                t.entry <= 0 or t.risk <= 0 or
                abs(t.entry.adjusted()) > 18 or abs(t.risk.adjusted()) > 18 or
                (t.gross_r is not None and
                 (type(t.gross_r) is not D or not t.gross_r.is_finite() or
                  abs(t.gross_r.adjusted()) > 18))):
            raise ValueError("Invalid declared entered-trade geometry")
        if previous is not None and t.time <= previous:
            raise ValueError("Entered positions must be globally strictly chronological")
        previous = t.time
        by_cohort[t.cohort].append(t)
    result = {}
    with localcontext() as ctx:
        ctx.prec = 80
        for name, group in by_cohort.items():
            n = len(group)
            observed = [t for t in group if t.gross_r is not None]
            missing = n - len(observed)
            gross_known = sum((t.gross_r for t in observed), D(0))
            cost_units = sum((t.entry / (D(10000) * t.risk) for t in group), D(0))
            scenarios = []
            for bps in COST_BPS:
                cost = cost_units * bps
                low = ((gross_known + missing * missing_gross_lower - cost) / n
                       if n else None)
                high = ((gross_known + missing * missing_gross_upper - cost) / n
                        if n else None)
                needed = (cost - gross_known) / missing if missing else None
                scenarios.append({
                    "additional_round_trip_bps": bps,
                    "conditional_lower_mean_net_r": str(low) if low is not None else None,
                    "conditional_upper_mean_net_r": str(high) if high is not None else None,
                    "required_mean_missing_gross_r_for_zero_net": (
                        str(needed) if needed is not None else None),
                    "zero_net_possible_within_declared_bounds": (
                        missing_gross_lower <= needed <= missing_gross_upper
                        if needed is not None else None),
                    "all_entered_mean_net_r_fully_observed": (
                        str(low) if not missing and n else None),
                })
            result[name] = {
                "entered_positions": n,
                "observed_outcomes": len(observed),
                "censored_unknown_exits": missing,
                "conditional_missing_gross_r_lower": str(missing_gross_lower),
                "conditional_missing_gross_r_upper": str(missing_gross_upper),
                "scenarios": scenarios,
            }
    return {
        "audit": "DECLARED_CENSORED_EXIT_BOUNDS_V1",
        "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC",
        "assumptions_are_verified_exit_limits": False,
        "unknown_exit_returns_imputed": False,
        "all_entered_costs_are_illustrative_not_broker_verified": True,
        "bounds_are_statistical_confidence_intervals": False,
        "independent_holdout_verified": False,
        "verified_profitability": False,
        "may_select_strategy_from_result": False,
        "may_execute_order": False,
        "cohorts": result,
    }
