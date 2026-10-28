"""Synthetic regression coverage for censor-aware entered-position blocks."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest

from app.offline_sweep_censor_aware_blocks import (
    EnteredTrade, audit_censor_aware_blocks as audit)


def rows(values=("1", None, "-1", None), cohort="development"):
    return [EnteredTrade(datetime(2025, 1, 1) + timedelta(minutes=i),
                         cohort, D(value) if value is not None else None,
                         D("100"), D("2"))
            for i, value in enumerate(values)]


def run(data=None, **kwargs):
    return audit(rows() if data is None else data, block_length=2,
                 resamples=50, **kwargs)


def test_reproducible_and_no_trading_authority():
    report = run()
    assert report == run()
    assert report["missing_exits_imputed"] is False
    assert report["may_execute_order"] is False
    assert report["verified_profitability"] is False
    assert report["bands_are_calibrated_confidence_intervals"] is False


def test_censored_remains_in_original_block_population():
    report = run()["cohorts"]["development"]
    assert (report["entered_positions"], report["observed_outcomes"],
            report["censored_unknown_exits"]) == (4, 2, 2)
    assert report["original_censored_fraction"] == "0.5"
    assert report["draws_completed"] == 50
    assert D(report["descriptive_p025_censored_fraction"]) >= 0
    assert D(report["descriptive_p975_censored_fraction"]) <= 1


def test_exact_cost_geometry_and_monotonicity():
    scenarios = run()["cohorts"]["development"]["scenarios"]
    assert [D(x["observed_mean_net_r"]) for x in scenarios] == [
        D("0"), D("-0.025"), D("-0.05"), D("-0.10")]
    assert all(D(scenarios[i]["descriptive_p025_observed_mean_net_r"]) >=
               D(scenarios[i+1]["descriptive_p025_observed_mean_net_r"])
               for i in range(3))
    assert all(x["draws_with_observed_exits"] +
               x["draws_with_no_observed_exits"] == 50 for x in scenarios)


def test_single_censored_neighbor_still_allows_two_position_blocks():
    r = run(rows(("1", None)))["cohorts"]["development"]
    assert D(r["scenarios"][0]["descriptive_p025_observed_mean_net_r"]) == D("1")
    assert D(r["scenarios"][1]["descriptive_p975_observed_mean_net_r"]) == D("0.975")
    assert r["original_censored_fraction"] == "0.5"


def test_all_censored_never_invents_returns():
    r = run(rows((None, None, None)))["cohorts"]["development"]
    assert r["draws_completed"] == 50
    assert r["original_censored_fraction"] == "1"
    assert r["scenarios"][0]["observed_mean_net_r"] is None
    assert r["scenarios"][0]["descriptive_p975_observed_mean_net_r"] is None
    assert r["scenarios"][0]["draws_with_no_observed_exits"] == 50


def test_empty_and_short_samples_have_no_fabricated_bands():
    for data in ([], rows(("1",))):
        r = run(data)["cohorts"]["development"]
        assert r["draws_completed"] == 0
        assert r["descriptive_p025_censored_fraction"] is None
        assert r["scenarios"][0]["descriptive_p025_observed_mean_net_r"] is None


def test_deterministic_censored_draws_and_separate_cohorts():
    baseline = run()["cohorts"]["development"]
    later = [replace(t, time=t.time + timedelta(days=1),
                     cohort="exploratory_later") for t in rows(("9", None))]
    both = run(rows()+later)["cohorts"]
    assert both["development"] == baseline
    assert both["exploratory_later"]["censored_unknown_exits"] == 1


def test_zero_observed_draws_are_counted_not_imputed():
    r = run(rows((None, None, None, "1", None, None)))["cohorts"]["development"]
    assert r["scenarios"][0]["draws_with_no_observed_exits"] > 0
    assert r["scenarios"][0]["draws_with_observed_exits"] > 0


def test_does_not_mutate_input_or_expose_raw_source_times():
    data = rows()
    before = tuple(data)
    report = run(data)
    assert tuple(data) == before
    assert "2025-01-01" not in str(report)


@pytest.mark.parametrize("kwargs", [
    {"block_length": 0}, {"block_length": True}, {"resamples": 0},
    {"resamples": 1001}, {"seed": -1}, {"seed": 2**63},
])
def test_bad_controls_fail_closed(kwargs):
    with pytest.raises(ValueError):
        audit(rows(), **kwargs)


@pytest.mark.parametrize("change", [
    {"gross_r": D("NaN")}, {"gross_r": D("Infinity")},
    {"entry": D(0)}, {"risk": D("-1")}, {"entry": 100},
    {"cohort": "other"}, {"time": datetime(2025, 1, 1, tzinfo=timezone.utc)},
])
def test_bad_trade_geometry_fail_closed(change):
    data = rows()
    data[0] = replace(data[0], **change)
    with pytest.raises(ValueError):
        run(data)


def test_duplicate_timestamp_fail_closed():
    data = rows()
    data[1] = replace(data[1], time=data[0].time)
    with pytest.raises(ValueError):
        run(data)


def test_work_budget_fail_closed():
    data = [EnteredTrade(datetime(2025, 1, 1)+timedelta(minutes=i),
                         "development", D(1), D(100), D(2)) for i in range(2001)]
    with pytest.raises(ValueError, match="budget"):
        audit(data, resamples=1000)


def test_invalid_input_container_fail_closed():
    with pytest.raises(ValueError):
        audit(iter(rows()))
