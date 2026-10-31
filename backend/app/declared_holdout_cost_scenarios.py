"""Offline adverse per-observation cost scenarios for declared holdout results.

Never authenticates costs, market data, external anchors, or broker orders.
"""
from __future__ import annotations

from decimal import Decimal, localcontext

from .declared_holdout_cost_attribution import audit_declared_holdout_cost_attribution
from .declared_holdout_release_gate import _exact, _id, _money

_SCENARIO = {
    "scenario_id", "spread_extra_cash_per_observation",
    "slippage_extra_cash_per_observation",
    "commission_extra_cash_per_observation",
    "financing_extra_cash_per_observation",
    "fx_extra_cash_per_observation",
}
_EXTRA = tuple(sorted(_SCENARIO - {"scenario_id"}))


def audit_declared_holdout_cost_scenarios(
    manifest, census, anchor, outcomes, release_at_utc, scenarios
):
    """Apply nonnegative additional declared costs after the full release audit.

    Each scenario adds a fixed cash debit *per observation*, not a percentage,
    price spread, executable quote, or broker-specific financing estimate.
    Small holdouts never disclose outcome-derived net or cost totals.
    """
    if type(scenarios) is not list or not 1 <= len(scenarios) <= 8:
        raise ValueError("Expected one to eight declared stress scenarios")
    parsed, ids = [], set()
    for item in scenarios:
        _exact(item, _SCENARIO, "cost stress scenario")
        name = item["scenario_id"]
        if not _id(name) or name in ids:
            raise ValueError("Invalid or repeated stress scenario identity")
        ids.add(name)
        increments = {field: _money(item[field], nonnegative=True)
                      for field in _EXTRA}
        parsed.append((name, increments))
    # Do not access cost or outcome totals before the underlying release audit.
    baseline = audit_declared_holdout_cost_attribution(
        manifest, census, anchor, outcomes, release_at_utc
    )
    withheld = baseline["outcome_metrics_withheld"]
    count = baseline["observation_count"]
    rows = []
    with localcontext() as ctx:
        ctx.prec = 80
        baseline_net = None if withheld else Decimal(baseline["net_cash"])
        for name, increments in sorted(parsed, key=lambda item: item[0]):
            extra = sum(increments.values(), Decimal(0)) * count
            rows.append({
                "scenario_id": name,
                "extra_cost_cash": None if withheld else format(extra, ".4f"),
                "stressed_net_cash": None if withheld else
                    format(baseline_net - extra, ".4f"),
            })
        worst = None if withheld else min(
            rows, key=lambda item: (Decimal(item["stressed_net_cash"]),
                                    item["scenario_id"])
        )
    return {
        "protocol": "declared-holdout-adverse-cost-scenarios-v1",
        "status": baseline["status"],
        "manifest_sha256": baseline["manifest_sha256"],
        "outcome_receipts_sha256": baseline["outcome_receipts_sha256"],
        "observation_count": count,
        "outcome_metrics_withheld": withheld,
        "baseline_net_cash": baseline["net_cash"],
        "scenarios": rows,
        "worst_scenario_id": None if withheld else worst["scenario_id"],
        "worst_stressed_net_cash": None if withheld else worst["stressed_net_cash"],
        "source_bytes_independently_authenticated": False,
        "holdout_untouched_independently_verified": False,
        "broker_costs_verified": False,
        "profitable_edge_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "Synthetic or caller-declared incremental cash debits only. "
                   "Not broker-calibrated, executable, or a trading recommendation.",
    }
