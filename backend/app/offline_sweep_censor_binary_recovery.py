"""Offline counterfactual recovery grid for censored sweep exits.

A declared binary +2R/-1R gross outcome assumption is NOT a return bound,
exit imputation, observed trade, broker fill, forecast or permission to trade.
The original research population and cost scenarios remain unchanged.
"""
import argparse
import json
from decimal import Decimal, ROUND_CEILING, localcontext
from pathlib import Path

from .offline_sweep_censor_threshold import (
    MAX_BYTES, _reject_duplicate_keys, audit_research,
)

WIN_GROSS_R = Decimal(2)
LOSS_GROSS_R = Decimal(-1)
WIN_MINUS_LOSS_R = WIN_GROSS_R - LOSS_GROSS_R


def audit_binary_recovery(payload):
    """Required censored +2R wins if all other censored outcomes are -1R.

    Runs the existing fail-closed frozen-protocol/cost/population validator
    first. No future observations are read and no trades are selected.
    """
    validated = audit_research(payload)
    result = {}
    with localcontext() as ctx:
        ctx.prec = 80
        for name, cohort in validated["cohorts"].items():
            n = cohort["censored_entered_outcomes"]
            entered = cohort["entered_positions"]
            rows = []
            for scenario in cohort["scenarios"]:
                observed_net = Decimal(scenario["observed_net_r_sum"])
                censored_cost = Decimal(
                    scenario["implied_censored_additional_cost_r_sum"])
                all_loss_net = observed_net - censored_cost + n * LOSS_GROSS_R
                all_win_net = observed_net - censored_cost + n * WIN_GROSS_R
                if n == 0:
                    minimum = None
                    state = "NO_CENSORED_EXITS"
                else:
                    needed = (Decimal(0) - all_loss_net) / WIN_MINUS_LOSS_R
                    if needed <= 0:
                        minimum = 0
                        state = "NONNEGATIVE_EVEN_IF_ALL_CENSORED_LOSE_1R"
                    elif needed > n:
                        minimum = None
                        state = "UNATTAINABLE_UNDER_DECLARED_BINARY_ASSUMPTION"
                    else:
                        minimum = int(needed.to_integral_value(
                            rounding=ROUND_CEILING))
                        state = "REQUIRES_CENSORED_2R_WINS"
                rows.append({
                    "additional_round_trip_bps": scenario["additional_round_trip_bps"],
                    "observed_outcomes": cohort["observed_outcomes"],
                    "censored_entered_outcomes": n,
                    "entered_positions": entered,
                    "all_censored_gross_minus_1r_net_sum": str(all_loss_net),
                    "all_censored_gross_plus_2r_net_sum": str(all_win_net),
                    "minimum_censored_plus_2r_wins_for_nonnegative_total": minimum,
                    "minimum_censored_plus_2r_win_fraction": (
                        str(Decimal(minimum) / n)
                        if minimum is not None and n else None),
                    "state": state,
                })
            result[name] = {"scenarios": rows}
    return {
        "protocol": "source-local-sweep-confirmation-v3",
        "population": "FROZEN_ENTERED_POSITIONS_WITH_CENSORED_EXITS",
        "assumed_censored_win_gross_r": "2",
        "assumed_censored_loss_gross_r": "-1",
        "interpretation": "BINARY_COUNTERFACTUAL_NOT_A_RETURN_BOUND_OR_EDGE",
        "source_authenticated": False,
        "untouched_holdout_verified": False,
        "executable_broker_costs": False,
        "may_execute_order": False,
        "cohorts": result,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="Existing local offline_sweep_probe JSON report")
    args = parser.parse_args(argv)
    path = Path(args.report)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Report exceeds bounded input size")
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    print(json.dumps(audit_binary_recovery(payload), sort_keys=True))


if __name__ == "__main__":
    main()
