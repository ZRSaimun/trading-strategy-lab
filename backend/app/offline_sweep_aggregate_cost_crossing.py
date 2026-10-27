"""Read-only 0-to-5-bps observed-only cost crossing for declared sweep aggregates.

This is an interpolation of rounded, already-inspected exploratory outcomes,
not an executable spread estimate, a prospective test, or order permission.
Unknown exits remain unknown. No crossing is extrapolated beyond 5 bps.
"""
import argparse
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

from .offline_sweep_aggregate_audit import STATES, audit_aggregate

_HALF_UNIT = Decimal("0.000005")
_DISPLAY_UNIT = Decimal("0.00000001")
_FIVE = Decimal(5)


def _crossing(gross, cost5, observed):
    if observed == 0:
        return {"status": "NO_OBSERVED_EXITS", "zero_crossing_extra_bps": None,
                "lower_bound_extra_bps": None, "upper_bound_extra_bps": None}
    # Each endpoint was rounded independently to five decimal places. A
    # reported zero is not evidence of an exact zero: its true sign may vary
    # by half a last place. Never claim a strict crossing or a definite
    # non-crossing when either endpoint's sign is unresolved by rounding.
    if gross <= -_HALF_UNIT:
        status = "NOT_STRICTLY_POSITIVE_AT_ZERO_BPS"
    elif cost5 >= _HALF_UNIT:
        status = "NO_STRICT_CROSSING_WITHIN_DECLARED_0_TO_5_BPS"
    elif gross <= _HALF_UNIT or cost5 >= -_HALF_UNIT:
        status = "ROUNDING_AMBIGUOUS_ENDPOINT"
    else:
        # A linear interpolation of the two declared *rounded* mean returns.
        # For a>0>b, t=5a/(a-b) increases with either endpoint. Thus
        # (a-e,b-e) and (a+e,b+e) give conservative rounding bounds.
        def t(a, b):
            return _FIVE * a / (a - b)
        lo = t(gross - _HALF_UNIT, cost5 - _HALF_UNIT)
        hi = t(gross + _HALF_UNIT, cost5 + _HALF_UNIT)
        return {"status": "ROUNDED_OBSERVED_ONLY_INTERPOLATED_CROSSING",
                "zero_crossing_extra_bps": str(t(gross, cost5).quantize(_DISPLAY_UNIT)),
                "lower_bound_extra_bps": str(lo.quantize(_DISPLAY_UNIT, rounding=ROUND_FLOOR)),
                "upper_bound_extra_bps": str(hi.quantize(_DISPLAY_UNIT, rounding=ROUND_CEILING))}
    return {"status": status, "zero_crossing_extra_bps": None,
            "lower_bound_extra_bps": None, "upper_bound_extra_bps": None}


def audit_cost_crossing(payload):
    """Reconcile the fixed eight-cell report before interpolating extra costs."""
    checked = audit_aggregate(payload)
    by_state = {row["state"]: row for row in payload["states"]}
    states = []
    sums = {"0": Decimal(0), "5": Decimal(0)}
    for name in STATES:
        row = by_state[name]
        observed = row["observed"]
        means = row["observed_mean_net_r_by_extra_bps"]
        a = Decimal(means["0"]) if observed else Decimal(0)
        b = Decimal(means["5"]) if observed else Decimal(0)
        sums["0"] += a * observed
        sums["5"] += b * observed
        states.append({"state": name, "observed": observed,
                       "censored": row["censored"],
                       **_crossing(a, b, observed)})
    n = checked["counts"]["observed"]
    overall = _crossing(sums["0"] / n, sums["5"] / n, n)
    return {
        "audit": "DECLARED_ROUNDED_OBSERVED_ONLY_COST_CROSSING_SENSITIVITY",
        "population": checked["population"],
        "by_state": states,
        "overall": {"observed": n, "censored": checked["counts"]["censored"],
                    **overall},
        "method": "linear_interpolation_only_between_declared_0_and_5_extra_bps",
        "rounding_bounds": "conservative_half_last_place_of_each_5dp_cell_mean",
        "unknown_exits_not_imputed": checked["counts"]["censored"],
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
    print(json.dumps(audit_cost_crossing(json.loads(args.aggregate_json.read_text(encoding="utf-8"))),
                     sort_keys=True))


if __name__ == "__main__":
    main()
