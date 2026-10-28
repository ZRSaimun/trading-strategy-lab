"""Synthetic-only verification of the declared censored binary recovery grid."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from app.offline_sweep_censor_binary_recovery import audit_binary_recovery


def report(observed=2, censored=2, gross=D(2)):
    entered = observed + censored
    costs, stresses = [], []
    for bps in (0, 5, 10, 20):
        observed_net = D(observed) * (gross - D(bps) / 50)
        censored_cost = D(censored) * D(bps) / 50
        costs.append(dict(additional_round_trip_bps=bps, count=observed,
                          sum_net_r=str(observed_net)))
        for loss in (1, 3, 5):
            stresses.append(dict(
                additional_round_trip_bps=bps,
                assumed_loss_per_censored_entered_r=str(-loss),
                entered_population=entered,
                observed_outcomes=observed,
                censored_entered_outcomes=censored,
                sum_net_r_if_assumption=str(
                    observed_net - censored_cost - D(loss * censored)),
            ))
    cohort = dict(
        observed_outcomes=observed,
        entered_positions=entered,
        censored_due_to_gaps_or_boundaries=censored,
        cost_scenarios=costs,
        censored_entered_loss_stress_scenarios=stresses,
    )
    return {"research": dict(
        protocol="source-local-sweep-confirmation-v3",
        source_authenticated=False, timezone_verified=False,
        untouched_holdout_verified=False, executable_broker_costs=False,
        verified_profitability=False, may_execute_order=False,
        cohorts={"development": deepcopy(cohort),
                 "exploratory_later": deepcopy(cohort)},
    )}


def test_positive_observed_returns_need_no_censored_wins():
    rows = audit_binary_recovery(report())["cohorts"]["development"]["scenarios"]
    assert [r["minimum_censored_plus_2r_wins_for_nonnegative_total"] for r in rows] == [0] * 4
    assert all(r["state"] == "NONNEGATIVE_EVEN_IF_ALL_CENSORED_LOSE_1R" for r in rows)


def test_negative_observed_returns_change_feasibility_with_cost():
    rows = audit_binary_recovery(report(gross=D(-2)))["cohorts"]["development"]["scenarios"]
    assert rows[0]["minimum_censored_plus_2r_wins_for_nonnegative_total"] == 2
    assert rows[0]["all_censored_gross_plus_2r_net_sum"] == "0"
    assert all(r["minimum_censored_plus_2r_wins_for_nonnegative_total"] is None for r in rows[1:])
    assert all(r["state"] == "UNATTAINABLE_UNDER_DECLARED_BINARY_ASSUMPTION" for r in rows[1:])


def test_zero_observed_returns_need_one_of_two_wins():
    rows = audit_binary_recovery(report(observed=0))["cohorts"]["development"]["scenarios"]
    assert rows[0]["minimum_censored_plus_2r_wins_for_nonnegative_total"] == 1
    assert rows[0]["minimum_censored_plus_2r_win_fraction"] == "0.5"
    assert rows[0]["all_censored_gross_minus_1r_net_sum"] == "-2"


def test_no_censored_outcomes_is_not_a_zero_win_rate_claim():
    rows = audit_binary_recovery(report(censored=0))["cohorts"]["development"]["scenarios"]
    assert all(r["state"] == "NO_CENSORED_EXITS" for r in rows)
    assert all(r["minimum_censored_plus_2r_win_fraction"] is None for r in rows)


def test_empty_entered_population_has_no_invented_returns():
    rows = audit_binary_recovery(report(observed=0, censored=0))["cohorts"]["development"]["scenarios"]
    assert all(r["entered_positions"] == 0 for r in rows)
    assert all(D(r["all_censored_gross_minus_1r_net_sum"]) == 0 for r in rows)


@pytest.mark.parametrize("observed,censored,gross", [
    (0, 1, D(0)), (0, 2, D(0)), (1, 2, D(-1)),
    (2, 2, D(-2)), (2, 2, D(2)), (5, 3, D("-0.4")),
])
def test_integer_threshold_is_minimal_when_attainable(observed, censored, gross):
    rows = audit_binary_recovery(report(observed, censored, gross))["cohorts"]["development"]["scenarios"]
    for row in rows:
        n = row["censored_entered_outcomes"]
        low = D(row["all_censored_gross_minus_1r_net_sum"])
        high = D(row["all_censored_gross_plus_2r_net_sum"])
        assert high - low == 3 * n
        k = row["minimum_censored_plus_2r_wins_for_nonnegative_total"]
        if not n:
            assert k is None
        elif k is None:
            assert high < 0
        else:
            assert 0 <= k <= n
            assert low + 3 * k >= 0
            if k > 0:
                assert low + 3 * (k - 1) < 0


def test_rejects_corrupted_cost_table_before_recovery_calculation():
    payload = report()
    payload["research"]["cohorts"]["development"]["cost_scenarios"][1]["sum_net_r"] = "999"
    with pytest.raises(ValueError):
        audit_binary_recovery(payload)


def test_rejects_any_claim_of_order_permission():
    payload = report()
    payload["research"]["may_execute_order"] = True
    with pytest.raises(ValueError):
        audit_binary_recovery(payload)
