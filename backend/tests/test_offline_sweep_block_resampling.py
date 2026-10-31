"""Synthetic, offline regression tests for observed-only block sensitivity."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from app.offline_sweep_block_resampling import Trade, audit_observed_block_resampling as audit


def rows(values=("1", "-1", "2", "-2")):
    return [Trade(datetime(2025, 1, 1)+timedelta(minutes=i), "development",
                  D(v) if v is not None else None, D("100"), D("2"))
            for i, v in enumerate(values)]


def run(data=None, **kwargs):
    return audit(rows() if data is None else data, block_length=2,
                 resamples=20, **kwargs)


def test_determinism_and_no_claims():
    a = run()
    assert a == run()
    assert a["bands_are_calibrated_confidence_intervals"] is False
    assert a["may_execute_order"] is False
    assert a["verified_profitability"] is False
    assert a["cohorts"]["development"]["resampling_available"]


def test_cost_sensitivity_monotone_and_exact():
    s = run()["cohorts"]["development"]["scenarios"]
    assert [x["additional_round_trip_bps"] for x in s] == [0, 5, 10, 20]
    assert [D(x["observed_mean_net_r"]) for x in s] == [
        D("0"), D("-0.025"), D("-0.05"), D("-0.10")]
    assert all(D(s[i]["descriptive_p025_mean_net_r"]) >=
               D(s[i+1]["descriptive_p025_mean_net_r"]) for i in range(3))


def test_censored_exit_never_imputed():
    c = run(rows(("1", None, "-1")))["cohorts"]["development"]
    assert (c["entered_positions"], c["observed_outcomes"],
            c["censored_unknown_exits"]) == (3, 2, 1)
    assert D(c["scenarios"][0]["observed_mean_net_r"]) == 0
    assert not c["unconditional_expectancy_inference_permitted"]


def test_empty_or_all_censored_returns_null():
    for data in ([], rows((None, None))):
        c = run(data)["cohorts"]["development"]
        assert not c["resampling_available"]
        assert c["scenarios"][0]["observed_mean_net_r"] is None
        assert c["scenarios"][0]["descriptive_p025_mean_net_r"] is None


def test_insufficient_block_length_does_not_fabricate_bands():
    c = run(rows(("1",)))["cohorts"]["development"]
    assert D(c["scenarios"][0]["observed_mean_net_r"]) == 1
    assert c["scenarios"][0]["descriptive_p975_mean_net_r"] is None


def test_independent_cohort_rng_and_count():
    baseline = run()["cohorts"]["development"]
    later = [replace(t, time=t.time+timedelta(days=1),
                     cohort="exploratory_later") for t in rows(("9", "9"))]
    report = run(rows()+later)
    assert report["cohorts"]["development"] == baseline
    assert report["cohorts"]["exploratory_later"]["observed_outcomes"] == 2


def test_risk_scaled_cost():
    s = run([replace(t, risk=D("1")) for t in rows(("1", "1"))])[
        "cohorts"]["development"]["scenarios"]
    assert s[1]["observed_mean_net_r"] == "0.95"


@pytest.mark.parametrize("args", [
    {"block_length": 0}, {"block_length": True}, {"resamples": 0},
    {"resamples": 1001}, {"seed": -1}, {"seed": 2**63},
])
def test_invalid_controls_fail_closed(args):
    with pytest.raises(ValueError):
        audit(rows(), **args)


@pytest.mark.parametrize("change", [
    {"gross_r": D("NaN")}, {"gross_r": D("Infinity")},
    {"entry": D("0")}, {"risk": D("-1")}, {"entry": 100},
    {"cohort": "unknown"}, {"time": datetime(2025, 1, 1, tzinfo=timezone.utc)},
])
def test_invalid_trade_fail_closed(change):
    data = rows()
    data[0] = replace(data[0], **change)
    with pytest.raises(ValueError):
        run(data)


def test_nonmonotone_time_fail_closed():
    data = rows()
    data[1] = replace(data[1], time=data[0].time)
    with pytest.raises(ValueError):
        run(data)


def test_work_budget_fail_closed():
    data = [Trade(datetime(2025, 1, 1)+timedelta(minutes=i),
                  "development", D(0), D(100), D(2)) for i in range(2001)]
    with pytest.raises(ValueError, match="budget"):
        audit(data, resamples=1000)


def test_no_raw_source_times_in_report():
    assert "2025-01-01T" not in str(run())
