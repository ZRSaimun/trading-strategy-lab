"""Offline row-specific adverse cash-cost stress for declared holdout observations.

All source, row, cost and registration evidence is caller-declared. This module
does not fetch quotes, modify outcomes, access brokers or authorize orders.
"""
from __future__ import annotations

from decimal import Decimal, localcontext

from .declared_holdout_cost_attribution import audit_declared_holdout_cost_attribution
from .declared_holdout_release_gate import _exact, _id, _money

_COSTS = (
    "spread_extra_cash", "slippage_extra_cash", "commission_extra_cash",
    "financing_extra_cash", "fx_extra_cash",
)
_ROW = {"observation_id", "row_sha256", "source_sha256", *_COSTS}
_SCENARIO = {"scenario_id", "adjustments"}


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
            totals = {field: Decimal(0) for field in _COSTS}
            maximum = Decimal(0)
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
            if seen != set(by_id):
                raise ValueError("Incomplete row-cost population")
            withheld = baseline["outcome_metrics_withheld"]
            extra = sum(totals.values(), Decimal(0))
            net = None if withheld else Decimal(baseline["net_cash"]) - extra
            reports.append({
                "scenario_id": name,
                "extra_cost_cash": None if withheld else format(extra, ".4f"),
                "stressed_net_cash": None if withheld else format(net, ".4f"),
                "max_single_observation_extra_cost_cash":
                    None if withheld else format(maximum, ".4f"),
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
                   "or intraperiod equity risk are verified.",
    }
