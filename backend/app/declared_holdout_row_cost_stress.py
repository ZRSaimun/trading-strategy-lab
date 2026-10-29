"""Offline row-specific adverse cash-cost stress for declared holdout observations.

All source, row, cost and registration evidence is caller-declared. This module
does not fetch quotes, modify outcomes, access brokers or authorize orders.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, localcontext

from .declared_holdout_cost_attribution import audit_declared_holdout_cost_attribution
from .declared_holdout_release_gate import _exact, _id, _money

_COSTS = (
    "spread_extra_cash", "slippage_extra_cash", "commission_extra_cash",
    "financing_extra_cash", "fx_extra_cash",
)
_ROW = {"observation_id", "row_sha256", "source_sha256", *_COSTS}
_SCENARIO = {"scenario_id", "adjustments"}



def _declared_receipt_risk(outcomes, stressed_nets):
    """Receipt-second cash diagnostics, never intraperiod broker equity risk."""
    batches = {}
    worst = None
    for row in outcomes:
        net = stressed_nets[row["observation_id"]]
        worst = net if worst is None else min(worst, net)
        batch = batches.setdefault(
            row["observed_at_utc"], [Decimal(0), Decimal(0), Decimal(0)]
        )
        batch[0] += net
        batch[1 if net >= 0 else 2] += net

    running = peak = drawdown = Decimal(0)
    adverse_running = adverse_peak = adverse_drawdown = Decimal(0)
    for observed_at in sorted(batches):
        batch_net, positive, negative = batches[observed_at]
        running += batch_net
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)

        # Same-second receipts have no trustworthy internal ordering.
        # A prior peak or all same-second credits before debits can each
        # produce the largest receipt-time cash drawdown.
        adverse_end = adverse_running + batch_net
        adverse_drawdown = max(
            adverse_drawdown,
            adverse_peak - (adverse_running + negative),
            -negative,
            adverse_peak - adverse_end,
        )
        adverse_peak = max(adverse_peak, adverse_running + positive)
        adverse_running = adverse_end
    return worst, drawdown, adverse_drawdown


def audit_declared_holdout_row_cost_stress(
    manifest, census, anchor, outcomes, release_at_utc, scenarios
):
    """Reconcile 1:1 per-row adverse costs against the full holdout release gate.

    Requiring one adjustment per observation (including explicit zero rows)
    prevents accidental omission of losing/expensive trades from a scenario.
    An adjustment is a declared additional settlement-currency cash debit,
    NOT a spread in price units, a broker quote, or an independently verified
    CFD financing rate. Outcome-derived metrics remain withheld below 30 rows.
    """
    if type(scenarios) is not list or not 1 <= len(scenarios) <= 8:
        raise ValueError("Expected one to eight declared row-cost scenarios")

    # Full holdout and exact-decimal outcome validation happens first.
    baseline = audit_declared_holdout_cost_attribution(
        manifest, census, anchor, outcomes, release_at_utc
    )
    by_id = {row["observation_id"]: row for row in census}
    names = set()
    reports = []
    with localcontext() as ctx:
        ctx.prec = 80
        for scenario in scenarios:
            _exact(scenario, _SCENARIO, "row-cost scenario")
            name = scenario["scenario_id"]
            if not _id(name) or name in names:
                raise ValueError("Invalid or duplicate row-cost scenario ID")
            names.add(name)
            adjustments = scenario["adjustments"]
            if type(adjustments) is not list or len(adjustments) != len(census):
                raise ValueError("Row-cost scenario must cover every holdout observation")
            seen = set()
            extra_by_id = {}
            totals = {field: Decimal(0) for field in _COSTS}
            maximum = Decimal(0)
            stressed_observations = 0
            for adjustment in adjustments:
                _exact(adjustment, _ROW, "row-cost adjustment")
                key = adjustment["observation_id"]
                original = by_id.get(key) if _id(key) else None
                if (original is None or key in seen or
                        adjustment["row_sha256"] != original["row_sha256"] or
                        adjustment["source_sha256"] != original["source_sha256"]):
                    raise ValueError("Duplicate, missing or cross-source row-cost identity")
                seen.add(key)
                per_row = Decimal(0)
                for field in _COSTS:
                    amount = _money(adjustment[field], nonnegative=True)
                    totals[field] += amount
                    per_row += amount
                maximum = max(maximum, per_row)
                if per_row > 0:
                    stressed_observations += 1
                extra_by_id[key] = per_row
            if seen != set(by_id):
                raise ValueError("Incomplete row-cost population")
            withheld = baseline["outcome_metrics_withheld"]
            extra = sum(totals.values(), Decimal(0))
            # Input concentration is diagnostic, not an executable-cost estimate.
            # Zero total additional cost has no defined largest-row share.
            max_share_bps = (
                None if withheld or extra == 0 else
                int((maximum * Decimal(10000) / extra).to_integral_value(
                    rounding=ROUND_FLOOR
                ))
            )
            net = None if withheld else Decimal(baseline["net_cash"]) - extra
            worst_row = drawdown = adverse_drawdown = None
            baseline_losing = stressed_losing = cost_induced_losing = None
            stressed_gross_loss = cost_induced_gross_loss = None
            largest_stressed_loss = Decimal(0)
            if not withheld:
                baseline_losing = stressed_losing = cost_induced_losing = 0
                stressed_gross_loss = cost_induced_gross_loss = Decimal(0)
                stressed_nets = {}
                for outcome in outcomes:
                    key = outcome["observation_id"]
                    charges = sum(
                        (_money(outcome[field], nonnegative=True)
                         for field in ("spread_cash", "slippage_cash",
                                       "commission_cash", "fx_cash")),
                        Decimal(0),
                    )
                    baseline_row_net = (
                        _money(outcome["gross_cash"]) - charges
                        - _money(outcome["financing_cash"])
                    )
                    stressed_row_net = baseline_row_net - extra_by_id[key]
                    stressed_nets[key] = stressed_row_net
                    if baseline_row_net < 0:
                        baseline_losing += 1
                    if stressed_row_net < 0:
                        stressed_losing += 1
                        stressed_gross_loss -= stressed_row_net
                        largest_stressed_loss = max(largest_stressed_loss, -stressed_row_net)
                        if baseline_row_net >= 0:
                            cost_induced_losing += 1
                            cost_induced_gross_loss -= stressed_row_net
                if stressed_losing < baseline_losing:
                    raise AssertionError("Adverse costs cannot reduce losing row count")
                if sum(stressed_nets.values(), Decimal(0)) != net:
                    raise AssertionError("Stressed per-row cash failed reconciliation")
                worst_row, drawdown, adverse_drawdown = _declared_receipt_risk(
                    outcomes, stressed_nets
                )
            reports.append({
                "scenario_id": name,
                "extra_cost_cash": None if withheld else format(extra, ".4f"),
                "stressed_net_cash": None if withheld else format(net, ".4f"),
                "max_single_observation_extra_cost_cash":
                    None if withheld else format(maximum, ".4f"),
                "additional_cost_affected_observation_count":
                    None if withheld else stressed_observations,
                "max_single_observation_extra_cost_share_bps": max_share_bps,
                "worst_observation_stressed_net_cash":
                    None if withheld else format(worst_row, ".4f"),
                "max_observation_end_drawdown_cash":
                    None if withheld else format(drawdown, ".4f"),
                "max_receipt_time_ordering_drawdown_cash_upper_bound":
                    None if withheld else format(adverse_drawdown, ".4f"),
                "baseline_losing_observation_count": baseline_losing,
                "stressed_losing_observation_count": stressed_losing,
                "additional_cost_induced_losing_observation_count": cost_induced_losing,
                "stressed_gross_loss_cash":
                    None if withheld else format(stressed_gross_loss, ".4f"),
                "additional_cost_induced_gross_loss_cash":
                    None if withheld else format(cost_induced_gross_loss, ".4f"),
                "max_single_stressed_loss_share_bps": (
                    None if withheld or stressed_gross_loss == 0 else
                    int((largest_stressed_loss * Decimal(10000) /
                         stressed_gross_loss).to_integral_value(rounding=ROUND_FLOOR))
                ),
                "extra_cost_by_component_cash": {
                    field: None if withheld else format(totals[field], ".4f")
                    for field in _COSTS
                },
            })
    reports.sort(key=lambda row: row["scenario_id"])
    withheld = baseline["outcome_metrics_withheld"]
    worst = None if withheld else min(
        reports, key=lambda row: (
            Decimal(row["stressed_net_cash"]), row["scenario_id"]
        )
    )
    return {
        "protocol": "declared-holdout-row-cost-stress-v1",
        "status": baseline["status"],
        "manifest_sha256": baseline["manifest_sha256"],
        "outcome_receipts_sha256": baseline["outcome_receipts_sha256"],
        "observation_count": baseline["observation_count"],
        "outcome_metrics_withheld": withheld,
        "baseline_net_cash": baseline["net_cash"],
        "scenarios": reports,
        "worst_scenario_id": None if withheld else worst["scenario_id"],
        "worst_stressed_net_cash": None if withheld else worst["stressed_net_cash"],
        "source_bytes_independently_authenticated": False,
        "holdout_untouched_independently_verified": False,
        "broker_costs_verified": False,
        "profitable_edge_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "Every per-row cash debit and source identity is caller-declared. "
                   "Full-row coverage is not broker calibration or independent "
                   "holdout protection. No executable quotes, financing, margin "
                   "or intraperiod equity risk are verified. Receipt-second cash "
                   "drawdowns, cost concentration and losing-observation counts do not bound "
                   "unobserved broker-equity losses.",
    }
