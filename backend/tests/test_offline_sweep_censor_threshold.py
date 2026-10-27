"""Synthetic-only checks for conditional censored-outcome break-even algebra."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from app.offline_sweep_censor_threshold import audit_research


def fixture(observed=2, censored=2):
    entered = observed + censored
    # Observed gross +2R per trade, each hypothetical 5bps costs 0.1R.
    cases = []
    stresses = []
    for bps in (0, 5, 10, 20):
        observed_net = D(observed) * (D(2) - D(bps) / 50)
        censored_cost = D(censored) * D(bps) / 50
        cases.append(dict(additional_round_trip_bps=bps, count=observed,
                          sum_net_r=str(observed_net)))
        for loss in (1, 3, 5):
            stresses.append(dict(additional_round_trip_bps=bps,
                                 assumed_loss_per_censored_entered_r=str(-loss),
                                 entered_population=entered,
                                 observed_outcomes=observed,
                                 censored_entered_outcomes=censored,
                                 sum_net_r_if_assumption=str(observed_net - censored_cost - D(loss*censored))))
    cohort = dict(observed_outcomes=observed, entered_positions=entered,
                  censored_due_to_gaps_or_boundaries=censored,
                  cost_scenarios=cases,
                  censored_entered_loss_stress_scenarios=stresses)
    return dict(research=dict(protocol="source-local-sweep-confirmation-v3",
                              source_authenticated=False, timezone_verified=False,
                              untouched_holdout_verified=False, executable_broker_costs=False,
                              verified_profitability=False, may_execute_order=False,
                              cohorts=dict(development=deepcopy(cohort), exploratory_later=deepcopy(cohort))))


def test_threshold_full_entered_population_and_costs():
    result = audit_research(fixture())
    rows = result["cohorts"]["development"]["scenarios"]
    assert [D(x["required_mean_censored_gross_r_for_zero_entered_net"]) for x in rows] == [
        D(2), D("1.8"), D("1.6"), D("1.2")]
    assert [D(x["implied_censored_additional_cost_r_sum"]) for x in rows] == [
        D(0), D("0.2"), D("0.4"), D("0.8")]
    assert not result["may_execute_order"]


def test_no_censored_exits_threshold_undefined():
    rows = audit_research(fixture(censored=0))["cohorts"]["development"]["scenarios"]
    assert all(x["required_mean_censored_gross_r_for_zero_entered_net"] is None for x in rows)


def test_empty_population_undefined():
    result = audit_research(fixture(observed=0, censored=0))
    assert result["cohorts"]["development"]["entered_positions"] == 0
    assert all(x["required_mean_censored_gross_r_for_zero_entered_net"] is None
               for x in result["cohorts"]["development"]["scenarios"])


@pytest.mark.parametrize("mutation", [
    lambda p: p["research"].update(may_execute_order=True),
    lambda p: p["research"].update(protocol="unknown"),
    lambda p: p["research"]["cohorts"]["development"].update(entered_positions=100),
    lambda p: p["research"]["cohorts"]["development"]["cost_scenarios"].pop(),
    lambda p: p["research"]["cohorts"]["development"]["cost_scenarios"][1].update(count=3),
    lambda p: p["research"]["cohorts"]["development"]["censored_entered_loss_stress_scenarios"][5].update(sum_net_r_if_assumption="999"),
    lambda p: p["research"]["cohorts"]["development"]["censored_entered_loss_stress_scenarios"][0].update(sum_net_r_if_assumption="NaN"),
])
def test_fail_closed_on_inconsistent_report(mutation):
    payload = fixture()
    mutation(payload)
    with pytest.raises((ValueError, KeyError)):
        audit_research(payload)
