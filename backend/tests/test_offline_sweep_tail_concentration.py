"""Synthetic-only outcome-tail research tests; no private archive dependencies."""
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from app.offline_sweep_probe import Bar, observed_cost_tail_census, research


def test_fixed_population_tail_concentration_and_extra_costs():
    trades = [(D(x), D(100), D(1)) for x in (-2, -1, 0, 1, 5)]
    result = observed_cost_tail_census(trades)
    assert result["population"] == "OBSERVED_ENTERED_OUTCOMES_ONLY"
    assert result["censored_outcomes_excluded_not_imputed"]
    assert [s["additional_round_trip_bps"] for s in result["scenarios"]] == [
        0, 5, 10, 20]
    gross = result["scenarios"][0]
    assert (gross["strictly_positive"], gross["exactly_zero"],
            gross["strictly_negative"]) == (2, 1, 2)
    assert gross["tail_count"] == 1
    assert D(gross["nearest_rank_p10_r"]) == -2
    assert D(gross["median_r"]) == 0
    assert D(gross["nearest_rank_p90_r"]) == 5
    assert D(gross["worst_tail_mean_r"]) == -2
    assert D(gross["best_tail_sum_r"]) == 5
    assert D(gross["mean_without_best_tail_r"]) == D("-0.5")
    five = result["scenarios"][1]
    assert (five["strictly_positive"], five["exactly_zero"],
            five["strictly_negative"]) == (2, 0, 3)
    assert D(five["nearest_rank_p10_r"]) == D("-2.05")
    assert D(five["median_r"]) == D("-0.05")
    assert D(five["mean_without_best_tail_r"]) == D("-0.55")


def test_empty_singleton_and_ceil_tenth_tail():
    empty = observed_cost_tail_census([])["scenarios"][0]
    assert empty["observed_outcomes"] == empty["tail_count"] == 0
    assert empty["median_r"] is None
    assert empty["mean_without_best_tail_r"] is None
    singleton = observed_cost_tail_census([(D(2), D(100), D(1))])["scenarios"][0]
    assert singleton["tail_count"] == 1
    assert singleton["mean_without_best_tail_r"] is None
    assert D(singleton["nearest_rank_p10_r"]) == D(2)
    assert D(singleton["nearest_rank_p90_r"]) == D(2)
    eleven = observed_cost_tail_census(
        [(D(i), D(100), D(1)) for i in range(11)])["scenarios"][0]
    assert eleven["tail_count"] == 2
    assert D(eleven["worst_tail_mean_r"]) == D("0.5")
    assert D(eleven["best_tail_sum_r"]) == D(19)


@pytest.mark.parametrize("bad", [
    (D(1), D(100), D(0)),
    (D(1), D(-100), D(1)),
    (D("NaN"), D(100), D(1)),
    (D(1), D("Infinity"), D(1)),
])
def test_reject_invalid_observed_geometry(bad):
    with pytest.raises(ValueError, match="Invalid observed trade geometry"):
        observed_cost_tail_census([bad])


def test_research_tail_census_reconciles_to_existing_cost_scenarios():
    t = datetime(2025, 1, 1)
    bars = [Bar(t + timedelta(minutes=15 * i), D(100), D(101),
                D(99), D(100), 0) for i in range(200)]
    bars[30] = Bar(bars[30].time, D(100), D(101), D(98), D(100), 0)
    bars[31] = Bar(bars[31].time, D(100), D(103), D(99), D(102), 0)
    bars[32] = Bar(bars[32].time, D(103), D(114), D(97), D(100), 0)
    result = research(bars)
    for cohort in result["cohorts"].values():
        tail = cohort["observed_cost_tail_concentration_census"]
        assert [x["observed_outcomes"] for x in tail["scenarios"]] == [
            cohort["observed_outcomes"]] * 4
        for s, existing in zip(tail["scenarios"], cohort["cost_scenarios"]):
            assert s["strictly_positive"] == existing["strictly_positive"]
            assert s["strictly_positive"] + s["exactly_zero"] + (
                s["strictly_negative"]) == cohort["observed_outcomes"]
    assert not result["may_execute_order"]
    assert not result["verified_profitability"]
