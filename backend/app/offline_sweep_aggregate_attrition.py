"""Read-only attrition and illustrative cost-drag census of declared sweep cells.

This describes already-inspected rounded aggregates, not independent trades,
a confidence interval, broker execution evidence, or an order signal.
"""
import argparse
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
from pathlib import Path

from .offline_sweep_aggregate_audit import STATES, audit_aggregate, load_declared_aggregate

Q = Decimal
_HALF_ROUNDING_UNIT = Q("0.000005")
_OUTPUT_UNIT = Q("0.00000001")
_PERCENT_UNIT = Q("0.0001")


def _interval(centre, uncertainty):
    """Outward-round a conservative enclosure for five-place rounded means."""
    return {
        "central": str(centre.quantize(_OUTPUT_UNIT, rounding=ROUND_HALF_EVEN)),
        "min": str((centre - uncertainty).quantize(
            _OUTPUT_UNIT, rounding=ROUND_FLOOR)),
        "max": str((centre + uncertainty).quantize(
            _OUTPUT_UNIT, rounding=ROUND_CEILING)),
    }


def _percentage(numerator, denominator):
    """Descriptive ratio; null means no denominator, not zero attrition."""
    if denominator == 0:
        return None
    return str((Q(numerator) * 100 / denominator).quantize(
        _PERCENT_UNIT, rounding=ROUND_HALF_EVEN))


def _cell(state, row, total_observed):
    observed = row["observed"]
    entered = row["entered"]
    confirmed = row["confirmed"]
    means = row["observed_mean_net_r_by_extra_bps"]
    sums = {}
    for bps in ("0", "5"):
        sums[bps] = Q(means[bps]) * observed if observed else Q(0)
    uncertainty = _HALF_ROUNDING_UNIT * observed
    return {
        "state": state,
        "confirmed": confirmed,
        "entered": entered,
        "observed": observed,
        "unknown_exits": row["censored"],
        "missing_entry": row["missing_entry"],
        "invalid_geometry": row["invalid_geometry"],
        "observed_percent_of_entered_approx": _percentage(observed, entered),
        "unknown_exit_percent_of_entered_approx": _percentage(row["censored"], entered),
        "missing_entry_percent_of_confirmed_approx": _percentage(
            row["missing_entry"], confirmed),
        "observed_percent_of_all_observed_approx": _percentage(
            observed, total_observed),
        "observed_net_r_sum_by_extra_bps_rounded_mean_enclosure": {
            bps: _interval(sums[bps], uncertainty) if observed else None
            for bps in ("0", "5")
        },
        # Two independently rounded cell means: each may deviate by 0.5e-5R.
        "observed_net_r_cost_drag_0_to_5_bps_enclosure": (
            _interval(sums["0"] - sums["5"], uncertainty * 2)
            if observed else None),
    }


def audit_attrition_cost_drag(payload):
    """Reconcile before computing all-cell descriptive totals; never select."""
    checked = audit_aggregate(payload)
    rows = {row["state"]: row for row in payload["states"]}
    observed_total = checked["counts"]["observed"]
    cells = [_cell(state, rows[state], observed_total) for state in STATES]
    total_sums = {
        bps: sum((Q(rows[state]["observed_mean_net_r_by_extra_bps"][bps]) *
                  rows[state]["observed"] for state in STATES
                  if rows[state]["observed"]), Q(0))
        for bps in ("0", "5")
    }
    total_uncertainty = _HALF_ROUNDING_UNIT * observed_total
    counts = checked["counts"]
    return {
        "audit": "DECLARED_ROUNDED_AGGREGATE_ATTRITION_COST_DRAG_ONLY",
        "population": checked["population"],
        "counts": counts,
        "overall": {
            "observed_percent_of_entered_approx": _percentage(
                counts["observed"], counts["entered"]),
            "unknown_exit_percent_of_entered_approx": _percentage(
                counts["censored"], counts["entered"]),
            "missing_entry_percent_of_confirmed_approx": _percentage(
                counts["missing_entry"], counts["confirmed"]),
            "observed_net_r_sum_by_extra_bps_rounded_mean_enclosure": {
                bps: _interval(total_sums[bps], total_uncertainty)
                for bps in ("0", "5")
            },
            "observed_net_r_cost_drag_0_to_5_bps_enclosure": _interval(
                total_sums["0"] - total_sums["5"], total_uncertainty * 2),
        },
        "by_state": cells,
        "rounding": "conservative_independent_5dp_cell_mean_enclosures; percentage_4dp_approx",
        "costs": "ILLUSTRATIVE_EXTRA_ROUND_TRIP_BPS_NOT_EXECUTABLE",
        "unknown_exits_not_imputed": counts["censored"],
        "retrospective_descriptive_only": True,
        "source_authenticated": False,
        "independent_holdout_verified": False,
        "executable_broker_costs_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate_json", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(audit_attrition_cost_drag(
        load_declared_aggregate(args.aggregate_json)), sort_keys=True))


if __name__ == "__main__":
    main()
