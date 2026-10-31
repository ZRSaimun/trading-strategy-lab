from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.offline_sweep_censor_aware_blocks import EnteredTrade
from app.offline_sweep_censor_bounds import audit_censored_exit_bounds


def t(i, r, cohort="development", entry="100", risk="2"):
    return EnteredTrade(datetime(2025, 1, 1) + timedelta(minutes=i), cohort,
                        None if r is None else D(str(r)), D(entry), D(risk))


def test_known_and_unknown_zero_cost_bounds():
    x = audit_censored_exit_bounds([t(0, 1), t(1, None), t(2, -1)])
    c = x["cohorts"]["development"]
    assert (c["entered_positions"], c["censored_unknown_exits"]) == (3, 1)
    s = c["scenarios"][0]
    assert abs(D(s["conditional_lower_mean_net_r"]) - D(-1) / 3) < D("1e-27")
    assert abs(D(s["conditional_upper_mean_net_r"]) - D(1) / 3) < D("1e-27")
    assert D(s["required_mean_missing_gross_r_for_zero_net"]) == 0
    assert s["zero_net_possible_within_declared_bounds"] is True


def test_all_entered_cost_including_unknown():
    x = audit_censored_exit_bounds([t(0, 1), t(1, None)])
    s = x["cohorts"]["development"]["scenarios"][1]
    # 5 bps * 100 / (10000 * 2) = 0.025 R per entered position
    assert D(s["conditional_lower_mean_net_r"]) == D("-0.025")
    assert D(s["conditional_upper_mean_net_r"]) == D("0.975")
    assert D(s["required_mean_missing_gross_r_for_zero_net"]) == D("-0.95")


def test_all_observed_exact_not_missing_inference():
    x = audit_censored_exit_bounds([t(0, 1), t(1, -1)])
    s = x["cohorts"]["development"]["scenarios"][1]
    assert D(s["conditional_lower_mean_net_r"]) == D("-0.025")
    assert s["conditional_upper_mean_net_r"] == s["conditional_lower_mean_net_r"]
    assert s["required_mean_missing_gross_r_for_zero_net"] is None
    assert s["zero_net_possible_within_declared_bounds"] is None
    assert s["all_entered_mean_net_r_fully_observed"] is not None


def test_all_censored_not_invented():
    x = audit_censored_exit_bounds([t(0, None), t(1, None)])
    s = x["cohorts"]["development"]["scenarios"][0]
    assert D(s["conditional_lower_mean_net_r"]) == -1
    assert D(s["conditional_upper_mean_net_r"]) == 1
    assert x["unknown_exit_returns_imputed"] is False


def test_empty_cohort():
    x = audit_censored_exit_bounds([])
    for c in x["cohorts"].values():
        assert c["entered_positions"] == 0
        assert c["scenarios"][0]["conditional_lower_mean_net_r"] is None


def test_cohorts_separated():
    x = audit_censored_exit_bounds([t(0, 1), t(1, None, "exploratory_later")])
    assert x["cohorts"]["development"]["censored_unknown_exits"] == 0
    assert x["cohorts"]["exploratory_later"]["censored_unknown_exits"] == 1


def test_tighter_bounds_and_impossible_break_even():
    x = audit_censored_exit_bounds([t(0, -2), t(1, None)],
                                   missing_gross_lower=D("-0.5"),
                                   missing_gross_upper=D("0.5"))
    s = x["cohorts"]["development"]["scenarios"][0]
    assert s["zero_net_possible_within_declared_bounds"] is False
    assert D(s["conditional_upper_mean_net_r"]) < 0


@pytest.mark.parametrize("bad", [(-1, 1), (D("NaN"), D(1)),
                                 (D("Infinity"), D(1)), (D(2), D(1)),
                                 (D("1e7"), D("1e7"))])
def test_invalid_bound_inputs(bad):
    with pytest.raises(ValueError):
        audit_censored_exit_bounds([], missing_gross_lower=bad[0],
                                   missing_gross_upper=bad[1])


@pytest.mark.parametrize("bad", [
    [t(1, 1), t(0, 0)],
    [t(0, 1), t(0, 1)],
    [t(0, "NaN")],
    [t(0, "Infinity")],
    [t(0, 1, entry="0")],
    [t(0, 1, risk="0")],
    [t(0, 1, cohort="not-a-cohort")],
    [EnteredTrade(datetime(2025, 1, 1, tzinfo=timezone.utc), "development", D(1), D(100), D(2))],
    ["not-a-trade"],
])
def test_invalid_trades(bad):
    with pytest.raises(ValueError):
        audit_censored_exit_bounds(bad)


def test_no_prices_timestamps_or_individual_trades_in_report():
    x = audit_censored_exit_bounds([t(0, None, entry="123.456", risk="7.89")])
    text = repr(x)
    assert "123.456" not in text and "2025-01-01" not in text
    assert x["may_execute_order"] is False
    assert x["verified_profitability"] is False


def test_reproducible():
    a = [t(0, 1), t(1, None), t(2, -1)]
    assert audit_censored_exit_bounds(a) == audit_censored_exit_bounds(tuple(a))
