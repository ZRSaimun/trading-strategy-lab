"""Read-only, declared-only break-even sensitivity for offline sweep probe JSON.

No prices, broker quotes, credentials, orders, or private archive reads.
This algebra does not impute missing exits or establish an edge.
"""
import argparse
import json
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

COSTS = (0, 5, 10, 20)
LOSSES = (1, 3, 5)
MAX_BYTES = 20_000_000


def _decimal(value):
    if not isinstance(value, str):
        raise ValueError("Expected a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite decimal")
    return result


def _close(a, b):
    return abs(a - b) <= Decimal("1e-25") * max(Decimal(1), abs(a), abs(b))


def _unique(rows, key, expected):
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("Missing or duplicated scenario population")
    mapped = {}
    for row in rows:
        k = key(row)
        if k in mapped or k not in expected:
            raise ValueError("Unknown or duplicated scenario")
        mapped[k] = row
    if set(mapped) != set(expected):
        raise ValueError("Incomplete scenario population")
    return mapped


def audit_research(payload):
    """Compute conditional missing-exit gross-R thresholds without changing trades.

    The required mean of censored *gross* R for full entered-position net sum
    to reach zero is (observed net sum - censored additional costs)/N_censored.
    The threshold is not an observed outcome, loss bound or broker forecast.
    """
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    report = payload.get("research", payload)
    if not isinstance(report, dict) or report.get("protocol") != "source-local-sweep-confirmation-v3":
        raise ValueError("Unsupported or missing frozen protocol")
    for flag in ("source_authenticated", "timezone_verified", "untouched_holdout_verified",
                 "executable_broker_costs", "verified_profitability", "may_execute_order"):
        if report.get(flag) is not False:
            raise ValueError("Unexpected source or execution assurance flag")
    cohorts = report.get("cohorts")
    if not isinstance(cohorts, dict) or set(cohorts) != {"development", "exploratory_later"}:
        raise ValueError("Unexpected cohort population")
    result = {}
    with localcontext() as ctx:
        ctx.prec = 60
        for name, cohort in cohorts.items():
            observed = cohort.get("observed_outcomes")
            censored = cohort.get("censored_due_to_gaps_or_boundaries")
            entered = cohort.get("entered_positions")
            if any(type(x) is not int or x < 0 for x in (observed, censored, entered)) or entered != observed + censored:
                raise ValueError("Entered outcome population mismatch")
            cost = _unique(cohort.get("cost_scenarios"),
                           lambda x: x["additional_round_trip_bps"], COSTS)
            stress = _unique(cohort.get("censored_entered_loss_stress_scenarios"),
                             lambda x: (x["additional_round_trip_bps"],
                                        _decimal(x["assumed_loss_per_censored_entered_r"])),
                             {(bps, Decimal(-loss)) for bps in COSTS for loss in LOSSES})
            rows = []
            censored_costs = {}
            for bps in COSTS:
                c = cost[bps]
                if type(c.get("count")) is not int or c["count"] != observed:
                    raise ValueError("Observed cost population mismatch")
                observed_net = _decimal(c["sum_net_r"])
                s1 = stress[(bps, Decimal(-1))]
                for loss in LOSSES:
                    s = stress[(bps, Decimal(-loss))]
                    if (s.get("entered_population") != entered or
                            s.get("observed_outcomes") != observed or
                            s.get("censored_entered_outcomes") != censored):
                        raise ValueError("Stressed population mismatch")
                censored_cost = observed_net - Decimal(censored) - _decimal(s1["sum_net_r_if_assumption"])
                if censored_cost < 0 and not _close(censored_cost, Decimal(0)):
                    raise ValueError("Negative implied censored cost")
                for loss in LOSSES:
                    expected = observed_net - censored_cost - Decimal(loss * censored)
                    if not _close(expected, _decimal(stress[(bps, Decimal(-loss))]["sum_net_r_if_assumption"])):
                        raise ValueError("Inconsistent missing-outcome stress")
                censored_costs[bps] = censored_cost
                rows.append(dict(
                    additional_round_trip_bps=bps,
                    observed_outcomes=observed,
                    censored_entered_outcomes=censored,
                    required_mean_censored_gross_r_for_zero_entered_net=(
                        str((observed_net - censored_cost) / censored) if censored else None),
                    observed_net_r_sum=str(observed_net),
                    implied_censored_additional_cost_r_sum=str(censored_cost)))
            if not _close(censored_costs[0], Decimal(0)):
                raise ValueError("Nonzero censored cost at zero bps")
            for bps in (10, 20):
                if not _close(censored_costs[bps], censored_costs[5] * Decimal(bps) / 5):
                    raise ValueError("Nonlinear implied censored costs")
            result[name] = dict(entered_positions=entered, observed_outcomes=observed,
                                censored_entered_outcomes=censored, scenarios=rows)
    return dict(protocol="source-local-sweep-confirmation-v3",
                population="FROZEN_ENTERED_POSITIONS_WITH_CENSORED_EXITS",
                interpretation="CONDITIONAL_GROSS_R_THRESHOLD_NOT_IMPUTATION_OR_PROFITABILITY",
                source_authenticated=False, untouched_holdout_verified=False,
                executable_broker_costs=False, may_execute_order=False,
                cohorts=result)


def _reject_duplicate_keys(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("Duplicate JSON key")
        result[k] = v
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="Existing local offline_sweep_probe JSON report")
    args = parser.parse_args(argv)
    path = Path(args.report)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Report exceeds bounded input size")
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    print(json.dumps(audit_research(data), sort_keys=True))


if __name__ == "__main__":
    main()
