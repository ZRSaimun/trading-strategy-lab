"""Read-only net-R tipping points for unknown exits in declared confluence cells.

All means are rounded exploratory aggregates, not authenticated broker fills.
The unknown-exit threshold is a *net* outcome including any costs applicable
to those exits. It is not an imputed return, loss bound or trade signal.
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from .offline_sweep_aggregate_audit import STATES, audit_aggregate

_HALF_LAST_PLACE = Decimal("0.000005")
_OUTPUT_PLACE = Decimal("0.00000001")


def _tipping(observed, censored, weighted_observed_net_r):
    """Conservative interval from 5-decimal observed-cell mean rounding."""
    if censored == 0:
        return {"status": "NO_UNKNOWN_EXITS", "required_unknown_mean_net_r": None,
                "required_unknown_mean_net_r_min": None,
                "required_unknown_mean_net_r_max": None}
    centre = -weighted_observed_net_r / censored
    margin = _HALF_LAST_PLACE * observed / censored
    return {
        "status": "UNKNOWN_EXIT_TIPPING_POINT_ONLY",
        "required_unknown_mean_net_r": str(centre.quantize(_OUTPUT_PLACE)),
        "required_unknown_mean_net_r_min": str((centre - margin).quantize(_OUTPUT_PLACE)),
        "required_unknown_mean_net_r_max": str((centre + margin).quantize(_OUTPUT_PLACE)),
    }


def audit_censored_tipping(payload):
    """Reconcile the original declared report before deriving net-R thresholds."""
    checked = audit_aggregate(payload)
    by_state = {row["state"]: row for row in payload["states"]}
    results = []
    totals = {bps: Decimal(0) for bps in ("0", "5")}
    for state in STATES:
        row = by_state[state]
        observed, censored = row["observed"], row["censored"]
        scenario = {}
        for bps in ("0", "5"):
            mean = row["observed_mean_net_r_by_extra_bps"][bps]
            weighted = Decimal(mean) * observed if observed else Decimal(0)
            totals[bps] += weighted
            scenario[bps] = _tipping(observed, censored, weighted)
        results.append({"state": state, "observed": observed, "unknown_exits": censored,
                        "by_extra_bps": scenario})
    aggregate = {bps: _tipping(checked["counts"]["observed"],
                                checked["counts"]["censored"], totals[bps])
                 for bps in ("0", "5")}
    return {
        "audit": "DECLARED_ROUNDED_AGGREGATE_NET_EXIT_TIPPING_ONLY",
        "population": checked["population"],
        "states": results,
        "overall_by_extra_bps": aggregate,
        "unknown_exits_not_imputed": checked["counts"]["censored"],
        "rounding_interval": "inclusive_conservative_5_decimal_cell_means",
        "cost_interpretation": "required unknown exits are NET R under the stated illustrative scenario",
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
    result = audit_censored_tipping(json.loads(args.aggregate_json.read_text(encoding="utf-8")))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
