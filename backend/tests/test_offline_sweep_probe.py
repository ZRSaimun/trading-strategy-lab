"""Synthetic tests only; never depend on proprietary archive bytes."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zipfile import ZipFile
import pytest
from app.offline_sweep_probe import Bar, read_archive, research, prior_range_regime


def synthetic_bars():
    t = datetime(2025, 1, 1)
    rows = [Bar(t + timedelta(minutes=15*i), D(100), D(101), D(99), D(100), 0)
            for i in range(200)]
    rows[30] = Bar(rows[30].time, D(100), D(101), D(98), D(100), 0)
    rows[31] = Bar(rows[31].time, D(100), D(103), D(99), D(102), 0)
    rows[32] = Bar(rows[32].time, D(103), D(114), D(97), D(100), 0)
    return rows


def test_conservative_same_bar_stop_precedes_target():
    result = research(synthetic_bars())
    cases = result["cohorts"]["development"]["cost_scenarios"]
    assert cases[0]["count"] == 1
    assert D(cases[0]["mean_net_r"]) == -1
    assert D(cases[1]["mean_net_r"]) < -1
    assert [c["additional_round_trip_bps"] for c in cases] == [0, 5, 10, 20]
    assert result["cohorts"]["exploratory_later"]["cost_scenarios"][0]["count"] == 0
    assert not result["verified_profitability"] and not result["may_execute_order"]


def test_confirmation_causal_and_no_gap_crossing():
    rows = synthetic_bars()
    rows[31] = Bar(rows[31].time, D(100), D(101), D(99), D(100), 0)
    assert research(rows)["cohorts"]["development"]["cost_scenarios"][0]["count"] == 0
    rows = synthetic_bars()
    rows[31] = Bar(rows[31].time, D(100), D(103), D(99), D(102), 1)
    assert research(rows)["cohorts"]["development"]["cost_scenarios"][0]["count"] == 0


def test_archive_read_only_complete_buckets(tmp_path):
    path = tmp_path / "sample.zip"
    rows = []
    t = datetime(2025, 1, 1)
    for i in list(range(15)) + list(range(20, 23)):
        rows.append((t + timedelta(minutes=i)).strftime("%Y%m%d %H%M%S") +
                    ";100;101;99;100;0\n")
    with ZipFile(path, "w") as z:
        z.writestr("DAT_ASCII_XAUUSD_M1_2025.csv", "".join(rows))
    bars, q = read_archive(path)
    assert len(bars) == 1
    assert q["complete_15m"] == 1 and q["discarded_partial_15m"] == 1
    assert q["discontinuities"] == 1
    assert q["timezone"] == "UNVERIFIED_SOURCE_LOCAL"


def test_archive_rejects_invalid_price_and_nested_csv(tmp_path):
    path = tmp_path / "bad.zip"
    with ZipFile(path, "w") as z:
        z.writestr("DAT_ASCII_XAUUSD_M1_2025.csv",
                   "20250101 000000;100;99;98;100;0\n")
    with pytest.raises(ValueError, match="Invalid M1 row"):
        read_archive(path)
    with ZipFile(path, "w") as z:
        z.writestr("dir/DAT_ASCII_XAUUSD_M1_2025.csv",
                   "20250101 000000;100;101;99;100;0\n")
    with pytest.raises(ValueError, match="flat CSV"):
        read_archive(path)


def test_fail_closed_protocol_inputs():
    with pytest.raises(ValueError):
        research(synthetic_bars(), embargo=1, horizon=16)


def test_invalid_minute_alignment_and_volume(tmp_path):
    path = tmp_path / "bad.zip"
    for row in ("20250101 000001;100;101;99;100;0\n",
                "20250101 000000;100;101;99;100;NaN\n"):
        with ZipFile(path, "w") as z:
            z.writestr("DAT_ASCII_XAUUSD_M1_2025.csv", row)
        with pytest.raises(ValueError, match="Invalid M1 row"):
            read_archive(path)


def test_censored_entry_reserves_full_horizon_no_overlapping_hypotheses():
    # A long remains unresolved when a continuity segment ends. A later short
    # also qualifies before the gap, but must NOT be admitted while that
    # censored long's holding horizon is still reserved.
    rows = synthetic_bars()
    replacements = {
        30: (100, 101, 80, 100),  # long sweep; stop 80, target 149
        31: (100, 103, 99, 102),  # long confirmation
        32: (103, 104, 99, 103),  # long hypothetical entry
        33: (103, 106, 101, 103), # short sweep; high above prior 104
        34: (101, 102, 99, 100),  # short confirmation
        35: (100, 101, 99, 100),  # short hypothetical entry if not blocked
    }
    for i, (o, h, l, c) in replacements.items():
        b = rows[i]
        rows[i] = Bar(b.time, D(o), D(h), D(l), D(c), 0)
    rows[37:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[37:]]
    result = research(rows)
    development = result["cohorts"]["development"]
    assert development["censored_due_to_gaps_or_boundaries"] == 1
    assert development["cost_scenarios"][0]["count"] == 0
    assert result["may_execute_order"] is False


@pytest.mark.parametrize(
    "direction,signal,confirm,entry,adverse_bar",
    [
        ("long", (100, 101, 98, 100), (100, 103, 99, 102),
         (103, 110, 99, 103), (80, 114, 79, 100)),
        ("short", (100, 102, 99, 100), (100, 100, 97, 98),
         (97, 100, 90, 95), (120, 121, 86, 100)),
    ],
)
def test_adverse_source_open_gap_does_not_credit_exact_stop(
    direction, signal, confirm, entry, adverse_bar
):
    # Long: entry 103, stop 98, gap open 80 -> -23/5 = -4.6 R.
    # Short: entry 97, stop 102, gap open 120 -> -23/5 = -4.6 R.
    # Both gap bars ALSO touch the 2R target; stop-first still wins.
    rows = synthetic_bars()
    for index, values in zip((30, 31, 32, 33),
                             (signal, confirm, entry, adverse_bar)):
        b = rows[index]
        rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    result = research(rows)
    assert result["protocol"] == "source-local-sweep-confirmation-v3"
    cases = result["cohorts"]["development"]["cost_scenarios"]
    assert cases[0]["count"] == 1, direction
    assert D(cases[0]["mean_net_r"]) == D("-4.6"), direction
    assert D(cases[1]["mean_net_r"]) < D("-4.6")
    assert result["may_execute_order"] is False


def test_uncensored_positive_cohort_has_exact_cost_zero_crossing():
    # A single unambiguous +2R long: entry=103, stop=98, target=113.
    # Additional round-trip bps deduct (103/5)/10000 R per bp.
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(114), D(99), D(113), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    assert cohort["cost_scenarios"][0]["count"] == 1
    assert D(cohort["uncensored_mean_gross_r"]) == D(2)
    assert D(cohort["mean_r_cost_per_additional_bps"]) == D(103) / D(50000)
    threshold = D(cohort["positive_mean_break_even_additional_bps"])
    assert abs(threshold - D(100000) / D(103)) < D("0.00000001")
    for case in cohort["cost_scenarios"]:
        bps = D(case["additional_round_trip_bps"])
        assert D(case["mean_net_r"]) == D(2) - bps * D(103) / D(50000)
    assert research(rows)["may_execute_order"] is False


def test_cost_threshold_withheld_for_nonpositive_and_empty_cohorts():
    report = research(synthetic_bars())["cohorts"]
    loss = report["development"]
    empty = report["exploratory_later"]
    assert loss["cost_scenarios"][0]["count"] == 1
    assert D(loss["uncensored_mean_gross_r"]) == D(-1)
    assert loss["positive_mean_break_even_additional_bps"] is None
    assert empty["cost_scenarios"][0]["count"] == 0
    assert empty["uncensored_mean_gross_r"] is None
    assert empty["mean_r_cost_per_additional_bps"] is None
    assert empty["positive_mean_break_even_additional_bps"] is None


def test_confirmed_signal_with_missing_entry_is_censused_not_silently_dropped():
    rows = synthetic_bars()
    # The sweep at 30 and confirmation at 31 are fully observable. The entry
    # at 32 belongs to a new source segment, so its open cannot be used.
    b = rows[32]
    rows[32] = Bar(b.time, b.o, b.h, b.l, b.c, 1)
    report = research(rows)["cohorts"]["development"]
    assert report["confirmed_signals_without_observable_entry"] == 1
    assert report["censored_due_to_gaps_or_boundaries"] == 0
    assert report["cost_scenarios"][0]["count"] == 0


def test_confirmed_signal_at_archive_end_without_entry_is_censused():
    rows = synthetic_bars()
    # Remove the earlier trade; put a confirmed long in the final two bars.
    b = rows[30]
    rows[30] = Bar(b.time, D(100), D(101), D(99), D(100), 0)
    for index, values in ((198, (100, 101, 98, 100)),
                          (199, (100, 103, 99, 102))):
        b = rows[index]
        rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    report = research(rows)["cohorts"]["exploratory_later"]
    assert report["confirmed_signals_without_observable_entry"] == 1
    assert report["cost_scenarios"][0]["count"] == 0
    assert report["censored_due_to_gaps_or_boundaries"] == 0


def test_confirmed_signal_with_nonconsecutive_entry_is_censused():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time + timedelta(minutes=15), b.o, b.h, b.l, b.c, b.segment)
    report = research(rows)["cohorts"]["development"]
    assert report["confirmed_signals_without_observable_entry"] == 1
    assert report["cost_scenarios"][0]["count"] == 0


def test_frozen_signal_census_for_observed_stop_and_missing_entry():
    observed = research(synthetic_bars())["cohorts"]["development"]
    assert observed["confirmed_signals"] == 1
    assert observed["entered_positions"] == 1
    assert observed["observed_outcomes"] == 1
    assert observed["unresolved_or_unadmitted_signals"] == 0
    assert observed["all_confirmed_signals_resolved"] is True
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, b.o, b.h, b.l, b.c, 1)
    missing = research(rows)["cohorts"]["development"]
    assert missing["confirmed_signals"] == 1
    assert missing["confirmed_signals_without_observable_entry"] == 1
    assert missing["entered_positions"] == missing["observed_outcomes"] == 0
    assert missing["unresolved_or_unadmitted_signals"] == 1
    assert missing["all_confirmed_signals_resolved"] is False


def test_observed_entry_with_invalid_stop_geometry_is_not_silently_dropped():
    rows = synthetic_bars()
    b = rows[32]
    # Long signal stop=98, but next-bar open=97: nonpositive stop distance.
    rows[32] = Bar(b.time, D(97), D(114), D(97), D(100), b.segment)
    report = research(rows)["cohorts"]["development"]
    assert report["confirmed_signals"] == 1
    assert report["invalid_entry_stop_or_target_geometry"] == 1
    assert report["confirmed_signals_without_observable_entry"] == 0
    assert report["entered_positions"] == 0
    assert report["observed_outcomes"] == 0
    assert report["unresolved_or_unadmitted_signals"] == 1
    assert report["all_confirmed_signals_resolved"] is False


def test_confirmation_inside_embargo_cannot_qualify_development_signal():
    rows = synthetic_bars()
    b = rows[30]
    rows[30] = Bar(b.time, D(100), D(101), D(99), D(100), b.segment)
    # For 200 bars, split=140 and embargo=16; 123 is last development
    # sweep index, but confirmation at 124 is *inside* embargo.
    for index, values in ((123, (100, 101, 98, 100)),
                          (124, (100, 103, 99, 102))):
        b = rows[index]
        rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    result = research(rows)
    assert result["split_index"] == 140
    assert all(cohort["confirmed_signals"] == 0
               for cohort in result["cohorts"].values())


def test_censored_entered_signal_is_in_denominator_but_not_return_mean():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    rows[33:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[33:]]
    report = research(rows)["cohorts"]["development"]
    assert report["confirmed_signals"] == 1
    assert report["entered_positions"] == 1
    assert report["censored_due_to_gaps_or_boundaries"] == 1
    assert report["observed_outcomes"] == 0
    assert report["unresolved_or_unadmitted_signals"] == 1
    assert report["all_confirmed_signals_resolved"] is False
    assert report["cost_scenarios"][0]["mean_net_r"] is None


def test_censored_entered_outcomes_have_explicit_hypothetical_loss_stress():
    # First confirmed long is entered but becomes censored at a source break.
    # A later source-local long in the new segment completes at +2R.
    # No missing exit is silently credited as a flat or winning trade.
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    rows[33:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[33:]]
    for index, values in ((80, (100, 101, 98, 100)),
                          (81, (100, 103, 99, 102)),
                          (82, (103, 114, 99, 113))):
        b = rows[index]
        rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    assert cohort["confirmed_signals"] == 2
    assert cohort["entered_positions"] == 2
    assert cohort["observed_outcomes"] == 1
    assert cohort["censored_due_to_gaps_or_boundaries"] == 1
    assert D(cohort["uncensored_mean_gross_r"]) == D(2)
    scenarios = {
        (D(v["assumed_loss_per_censored_entered_r"]),
         v["additional_round_trip_bps"]): v
        for v in cohort["censored_entered_loss_stress_scenarios"]
    }
    assert len(scenarios) == 12
    assert D(scenarios[(D(-1), 0)]["mean_net_r_if_assumption"]) == D("0.5")
    assert D(scenarios[(D(-3), 0)]["mean_net_r_if_assumption"]) == D("-0.5")
    assert D(scenarios[(D(-5), 0)]["mean_net_r_if_assumption"]) == D("-1.5")
    # Both entered positions pay the illustrative cost, including the
    # censored position; each has entry=103 and stop-distance=5.
    assert D(scenarios[(D(-3), 5)]["mean_net_r_if_assumption"]) == (
        D("-0.5") - D(103) * D(5) / D(50000))
    assert all(v["interpretation"] ==
               "ILLUSTRATIVE_MISSING_EXIT_STRESS_NOT_A_LOWER_BOUND"
               for v in scenarios.values())


def test_censored_loss_stress_does_not_invent_unobservable_entry():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, b.o, b.h, b.l, b.c, 1)
    cohort = research(rows)["cohorts"]["development"]
    assert cohort["confirmed_signals_without_observable_entry"] == 1
    assert cohort["entered_positions"] == 0
    assert cohort["censored_due_to_gaps_or_boundaries"] == 0
    assert len(cohort["censored_entered_loss_stress_scenarios"]) == 12
    assert all(v["entered_population"] == 0 and
               v["mean_net_r_if_assumption"] is None and
               D(v["sum_net_r_if_assumption"]) == 0
               for v in cohort["censored_entered_loss_stress_scenarios"])


def test_no_censor_stress_equals_observed_cost_scenarios():
    cohort = research(synthetic_bars())["cohorts"]["development"]
    assert cohort["entered_positions"] == cohort["observed_outcomes"] == 1
    assert cohort["censored_due_to_gaps_or_boundaries"] == 0
    for scenario in cohort["censored_entered_loss_stress_scenarios"]:
        bps = scenario["additional_round_trip_bps"]
        original = next(x for x in cohort["cost_scenarios"]
                        if x["additional_round_trip_bps"] == bps)
        assert D(scenario["mean_net_r_if_assumption"]) == D(original["mean_net_r"])


def test_exit_path_census_regular_stop_and_empty_cohort():
    reports = research(synthetic_bars())["cohorts"]
    stop = reports["development"]["observed_exit_path_census"]
    assert stop["observed_outcomes_total"] == 1
    assert stop["stop_touch_without_adverse_open"] == 1
    assert stop["stop_touch_with_adverse_open"] == 0
    assert stop["target_touch"] == stop["horizon_close"] == 0
    assert D(stop["adverse_source_open_extra_loss_r_sum"]) == 0
    assert stop["adverse_source_open_extra_loss_r_max"] is None
    empty = reports["exploratory_later"]["observed_exit_path_census"]
    assert empty["observed_outcomes_total"] == 0
    assert sum(empty[k] for k in (
        "stop_touch_without_adverse_open", "stop_touch_with_adverse_open",
        "target_touch", "horizon_close")) == 0


@pytest.mark.parametrize("signal,confirm,entry,adverse_bar", [
    ((100, 101, 98, 100), (100, 103, 99, 102),
     (103, 110, 99, 103), (80, 114, 79, 100)),
    ((100, 102, 99, 100), (100, 100, 97, 98),
     (97, 100, 90, 95), (120, 121, 86, 100)),
])
def test_exit_path_census_adverse_source_open_long_and_short(
    signal, confirm, entry, adverse_bar
):
    rows = synthetic_bars()
    for index, values in zip((30, 31, 32, 33),
                             (signal, confirm, entry, adverse_bar)):
        b = rows[index]
        rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    paths = cohort["observed_exit_path_census"]
    assert paths["observed_outcomes_total"] == 1
    assert paths["stop_touch_with_adverse_open"] == 1
    assert paths["stop_touch_without_adverse_open"] == 0
    assert paths["target_touch"] == 0  # Stop-first even if target also touched.
    assert D(paths["adverse_source_open_extra_loss_r_sum"]) == D("3.6")
    assert D(paths["adverse_source_open_extra_loss_r_max"]) == D("3.6")
    assert paths["interpretation"] == "SOURCE_OHLC_PROXY_NOT_EXECUTABLE_FILLS"


def test_exit_path_census_target_and_horizon_close():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(114), D(99), D(113), b.segment)
    target = research(rows)["cohorts"]["development"]["observed_exit_path_census"]
    assert target["target_touch"] == target["observed_outcomes_total"] == 1
    assert target["horizon_close"] == 0
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    horizon = research(rows)["cohorts"]["development"]["observed_exit_path_census"]
    assert horizon["horizon_close"] == horizon["observed_outcomes_total"] == 1
    assert horizon["target_touch"] == 0
    assert horizon["stop_touch_without_adverse_open"] == 0


def test_exit_path_census_does_not_reclassify_censored_entry():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    rows[33:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[33:]]
    cohort = research(rows)["cohorts"]["development"]
    assert cohort["entered_positions"] == cohort["censored_due_to_gaps_or_boundaries"] == 1
    paths = cohort["observed_exit_path_census"]
    assert paths["observed_outcomes_total"] == 0
    assert sum(paths[k] for k in (
        "stop_touch_without_adverse_open", "stop_touch_with_adverse_open",
        "target_touch", "horizon_close")) == 0
    assert paths["adverse_source_open_extra_loss_r_max"] is None


@pytest.mark.parametrize("side,entry_bar,later_bar,expected", [
    ("long", (103, 114, 97, 100), None, "opens_between_barriers_order_unknown"),
    ("long", (103, 104, 99, 103), (80, 114, 79, 100),
     "opens_at_or_beyond_stop"),
    ("long", (103, 104, 99, 103), (115, 116, 97, 103),
     "opens_at_or_beyond_target"),
    ("long", (103, 104, 97, 100), None, None),
    ("long", (103, 114, 99, 113), None, None),
    ("short", (97, 104, 86, 95), None, "opens_between_barriers_order_unknown"),
    ("short", (97, 100, 90, 95), (120, 121, 86, 100),
     "opens_at_or_beyond_stop"),
    ("short", (97, 100, 90, 95), (86, 104, 85, 95),
     "opens_at_or_beyond_target"),
])
def test_same_bar_collision_source_open_census(side, entry_bar, later_bar, expected):
    rows = synthetic_bars()
    if side == "short":
        for index, values in ((30, (100, 102, 99, 100)),
                              (31, (100, 100, 97, 98))):
            b = rows[index]
            rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    b = rows[32]
    rows[32] = Bar(b.time, *(D(v) for v in entry_bar), b.segment)
    if later_bar is not None:
        b = rows[33]
        rows[33] = Bar(b.time, *(D(v) for v in later_bar), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    collisions = cohort["same_bar_stop_target_collision_census"]
    assert cohort["observed_outcomes"] == 1
    assert collisions["observed_outcomes_total"] == 1
    assert collisions["both_barriers_touched"] == int(expected is not None)
    for key in ("opens_at_or_beyond_stop", "opens_at_or_beyond_target",
                "opens_between_barriers_order_unknown"):
        assert collisions[key] == int(key == expected)
    uplift = 3 if expected in ("opens_at_or_beyond_target",
                               "opens_between_barriers_order_unknown") else 0
    assert D(collisions["fixed_cohort_target_first_uplift_r_sum"]) == D(uplift)
    assert D(collisions["fixed_cohort_target_first_uplift_r_per_observed"]) == D(uplift)
    assert collisions["interpretation"] == (
        "SOURCE_OHLC_FIXED_COHORT_SENSITIVITY_NOT_BACKTEST")
    # A collision audit is descriptive: the original stop-first outcomes
    # and illustrative cost deductions must remain untouched.
    if expected == "opens_at_or_beyond_stop":
        assert D(cohort["cost_scenarios"][0]["mean_net_r"]) < -1
    elif expected is not None:
        assert D(cohort["cost_scenarios"][0]["mean_net_r"]) == -1


def test_same_bar_collision_censored_and_empty_populations_are_not_imputed():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    rows[33:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[33:]]
    reports = research(rows)["cohorts"]
    assert reports["development"]["censored_due_to_gaps_or_boundaries"] == 1
    for cohort in reports.values():
        collision = cohort["same_bar_stop_target_collision_census"]
        assert collision["both_barriers_touched"] == 0
        assert collision["observed_outcomes_total"] == 0
        assert D(collision["fixed_cohort_target_first_uplift_r_sum"]) == 0
        assert collision["fixed_cohort_target_first_uplift_r_per_observed"] is None


def test_observed_holding_duration_same_bar_stop_and_time_cost_arithmetic():
    cohort = research(synthetic_bars())["cohorts"]["development"]
    duration = cohort["observed_holding_duration_census"]
    assert duration["observed_outcomes_total"] == 1
    assert duration["observed_holding_15m_bars_sum"] == 1
    assert duration["observed_holding_15m_bars_min"] == 1
    assert duration["observed_holding_15m_bars_max"] == 1
    assert D(duration["observed_holding_15m_bars_mean"]) == 1
    assert duration["censored_entered_positions"] == 0
    scenarios = cohort["illustrative_observed_time_cost_scenarios"]
    assert [D(x["illustrative_additional_bps_per_observed_15m_bar"])
            for x in scenarios] == [D("0"), D("0.05"), D("0.2")]
    # Entry 103, stop 98, risk 5; -1R gross, 5 bps round trip,
    # plus 0.2 bps for one observed source bar.
    assert D(scenarios[2]["mean_net_r"]) == D("-1.010712")
    assert D(scenarios[0]["mean_net_r"]) == D(
        cohort["cost_scenarios"][1]["mean_net_r"])


def test_observed_holding_duration_full_horizon_and_empty_later():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    reports = research(rows)["cohorts"]
    duration = reports["development"]["observed_holding_duration_census"]
    assert duration["observed_holding_15m_bars_sum"] == 16
    assert duration["observed_holding_15m_bars_min"] == 16
    assert duration["observed_holding_15m_bars_max"] == 16
    assert D(duration["observed_holding_15m_bars_mean"]) == 16
    empty = reports["exploratory_later"]
    assert empty["observed_holding_duration_census"]["observed_holding_15m_bars_min"] is None
    assert empty["illustrative_observed_time_cost_scenarios"][0]["mean_net_r"] is None


def test_censored_holding_prefix_does_not_invent_exit_or_financing():
    rows = synthetic_bars()
    b = rows[32]
    rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), b.segment)
    rows[33:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[33:]]
    cohort = research(rows)["cohorts"]["development"]
    duration = cohort["observed_holding_duration_census"]
    assert cohort["entered_positions"] == cohort["censored_due_to_gaps_or_boundaries"] == 1
    assert duration["observed_outcomes_total"] == 0
    assert duration["observed_holding_15m_bars_sum"] == 0
    assert duration["censored_observed_prefix_15m_bars_sum"] == 1
    assert duration["censored_observed_prefix_15m_bars_max"] == 1
    assert all(x["mean_net_r"] is None for x in
               cohort["illustrative_observed_time_cost_scenarios"])


def test_pre_signal_volatility_range_thresholds_are_exact_and_causal():
    def prior(half_width):
        bar = Bar(datetime(2025, 1, 1), D(100), D(100) + D(half_width),
                  D(100) - D(half_width), D(100), 0)
        return [bar] * 16
    assert prior_range_regime(prior("0.049")) == "LOW_LT_10_BPS"
    assert prior_range_regime(prior("0.05")) == "MID_10_TO_LT_30_BPS"
    assert prior_range_regime(prior("0.149")) == "MID_10_TO_LT_30_BPS"
    assert prior_range_regime(prior("0.15")) == "HIGH_GTE_30_BPS"
    with pytest.raises(ValueError, match="Missing pre-signal"):
        prior_range_regime([])


@pytest.mark.parametrize("half_width,expected", [
    ("0.04", "LOW_LT_10_BPS"),
    ("0.10", "MID_10_TO_LT_30_BPS"),
    ("1", "HIGH_GTE_30_BPS"),
])
def test_pre_signal_volatility_bins_reconcile_and_do_not_filter_trades(
    half_width, expected
):
    rows = synthetic_bars()
    # Keep the sweep strictly one-sided after narrowing the prior range:
    # otherwise the original high=101 also pierces the reduced prior high.
    b = rows[30]
    rows[30] = Bar(b.time, D(100), D(100), D(98), D(100), b.segment)
    for index in range(14, 30):
        b = rows[index]
        rows[index] = Bar(b.time, D(100), D(100) + D(half_width),
                          D(100) - D(half_width), D(100), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    census = cohort["pre_signal_volatility_regime_census"]
    assert census["fixed_thresholds_bps"] == [10, 30]
    assert census["lookback_completed_bars"] == 16
    assert cohort["confirmed_signals"] == cohort["entered_positions"] == 1
    assert cohort["observed_outcomes"] == 1
    for key, cell in census["regimes"].items():
        count = int(key == expected)
        assert cell["confirmed_signals"] == count
        assert cell["entered_positions"] == count
        assert cell["observed_outcomes"] == count
        assert cell["censored_entered_outcomes"] == 0
        assert cell["confirmed_signals_without_observable_entry"] == 0
        assert cell["invalid_entry_stop_or_target_geometry"] == 0
        for i, scenario in enumerate(cell["observed_only_cost_scenarios"]):
            assert scenario["observed_outcomes"] == count
            assert scenario["additional_round_trip_bps"] == (0, 5, 10, 20)[i]
            assert scenario["mean_net_r"] == (
                cohort["cost_scenarios"][i]["mean_net_r"] if count else None)


@pytest.mark.parametrize("mode", ["missing_entry", "censored", "invalid"])
def test_pre_signal_volatility_censuses_nonreturn_populations(mode):
    rows = synthetic_bars()
    b = rows[32]
    if mode == "missing_entry":
        rows[32] = Bar(b.time, b.o, b.h, b.l, b.c, 1)
    elif mode == "censored":
        rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), 0)
        rows[33:] = [Bar(x.time, x.o, x.h, x.l, x.c, 1) for x in rows[33:]]
    else:
        rows[32] = Bar(b.time, D(97), D(114), D(97), D(100), 0)
    cohort = research(rows)["cohorts"]["development"]
    bins = cohort["pre_signal_volatility_regime_census"]["regimes"]
    high = bins["HIGH_GTE_30_BPS"]
    assert high["confirmed_signals"] == 1
    assert high["observed_outcomes"] == 0
    assert high["confirmed_signals_without_observable_entry"] == int(
        mode == "missing_entry")
    assert high["censored_entered_outcomes"] == int(mode == "censored")
    assert high["invalid_entry_stop_or_target_geometry"] == int(mode == "invalid")
    assert high["entered_positions"] == int(mode == "censored")
    assert all(x["mean_net_r"] is None for x in high["observed_only_cost_scenarios"])
    assert all(x["confirmed_signals"] == 0 for key, x in bins.items()
               if key != "HIGH_GTE_30_BPS")


def test_volatility_bins_sum_to_original_cost_scenario_without_reweighting():
    cohort = research(synthetic_bars())["cohorts"]["development"]
    cells = cohort["pre_signal_volatility_regime_census"]["regimes"].values()
    for i, overall in enumerate(cohort["cost_scenarios"]):
        weighted_sum = sum(
            (D(cell["observed_only_cost_scenarios"][i]["mean_net_r"]) *
             cell["observed_outcomes"]
             for cell in cells if cell["observed_outcomes"]), D(0))
        assert weighted_sum == D(overall["sum_net_r"])


@pytest.mark.parametrize("side", ["LONG_SWEEP_LOW", "SHORT_SWEEP_HIGH"])
def test_direction_census_causal_signal_and_cost_reconciliation(side):
    rows = synthetic_bars()
    if side == "SHORT_SWEEP_HIGH":
        for index, values in ((30, (100, 102, 99, 100)),
                              (31, (100, 100, 97, 98)),
                              (32, (97, 103, 90, 95))):
            b = rows[index]
            rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    directions = cohort["confirmed_signal_direction_census"]
    assert directions["interpretation"] == (
        "CAUSAL_DIRECTIONAL_ATTRITION_OBSERVED_ONLY_NOT_EDGE")
    assert cohort["confirmed_signals"] == cohort["entered_positions"] == 1
    assert cohort["observed_outcomes"] == 1
    for key, cell in directions["directions"].items():
        n = int(key == side)
        assert cell["confirmed_signals"] == n
        assert cell["entered_positions"] == n
        assert cell["observed_outcomes"] == n
        assert cell["confirmed_signals_without_observable_entry"] == 0
        assert cell["invalid_entry_stop_or_target_geometry"] == 0
        assert cell["censored_entered_outcomes"] == 0
        for i, case in enumerate(cell["observed_only_cost_scenarios"]):
            assert case["additional_round_trip_bps"] == (0, 5, 10, 20)[i]
            assert case["observed_outcomes"] == n
            assert case["mean_net_r"] == (
                cohort["cost_scenarios"][i]["mean_net_r"] if n else None)
    assert research(rows)["may_execute_order"] is False


@pytest.mark.parametrize("mode", ["missing_entry", "censored", "invalid"])
def test_direction_census_keeps_nonreturn_long_signals(mode):
    rows = synthetic_bars()
    b = rows[32]
    if mode == "missing_entry":
        rows[32] = Bar(b.time, b.o, b.h, b.l, b.c, 1)
    elif mode == "censored":
        rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), 0)
        rows[33:] = [Bar(x.time, x.o, x.h, x.l, x.c, 1) for x in rows[33:]]
    else:
        rows[32] = Bar(b.time, D(97), D(114), D(97), D(100), 0)
    cohort = research(rows)["cohorts"]["development"]
    sides = cohort["confirmed_signal_direction_census"]["directions"]
    long = sides["LONG_SWEEP_LOW"]
    short = sides["SHORT_SWEEP_HIGH"]
    assert long["confirmed_signals"] == 1
    assert long["observed_outcomes"] == 0
    assert long["confirmed_signals_without_observable_entry"] == int(
        mode == "missing_entry")
    assert long["invalid_entry_stop_or_target_geometry"] == int(mode == "invalid")
    assert long["censored_entered_outcomes"] == int(mode == "censored")
    assert long["entered_positions"] == int(mode == "censored")
    assert short["confirmed_signals"] == short["entered_positions"] == 0
    assert all(c["mean_net_r"] is None for c in
               long["observed_only_cost_scenarios"])


def test_direction_census_empty_cohort_has_no_invented_return():
    later = research(synthetic_bars())["cohorts"]["exploratory_later"]
    for side in later["confirmed_signal_direction_census"]["directions"].values():
        assert side["confirmed_signals"] == side["entered_positions"] == 0
        assert all(x["mean_net_r"] is None for x in
                   side["observed_only_cost_scenarios"])


@pytest.mark.parametrize("side", ["long", "short"])
def test_confirmation_three_candle_fvg_is_causal_and_does_not_filter(side):
    rows = synthetic_bars()
    if side == "long":
        b = rows[31]
        rows[31] = Bar(b.time, D(102), D(105), D(102), D(104), b.segment)
    else:
        for index, values in (
            (30, (100, 102, 99, 100)),
            (31, (98, 98, 95, 96)),
            (32, (97, 103, 90, 95)),
        ):
            b = rows[index]
            rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    cohort = research(rows)["cohorts"]["development"]
    fvg = cohort["confirmation_three_candle_fvg_census"]
    yes = fvg["states"]["SAME_DIRECTION_THREE_CANDLE_FVG"]
    no = fvg["states"]["NO_SAME_DIRECTION_THREE_CANDLE_FVG"]
    assert cohort["confirmed_signals"] == cohort["entered_positions"] == 1
    assert cohort["observed_outcomes"] == 1
    assert yes["confirmed_signals"] == yes["entered_positions"] == 1
    assert yes["observed_outcomes"] == 1
    assert no["confirmed_signals"] == no["entered_positions"] == 0
    for i, scenario in enumerate(yes["observed_only_cost_scenarios"]):
        assert scenario["mean_net_r"] == cohort["cost_scenarios"][i]["mean_net_r"]
        assert scenario["additional_round_trip_bps"] == (0, 5, 10, 20)[i]
    assert research(rows)["may_execute_order"] is False


@pytest.mark.parametrize("mode", ["missing_entry", "censored", "invalid"])
def test_confirmation_fvg_retains_all_nonreturn_signal_populations(mode):
    rows = synthetic_bars()
    b = rows[31]
    rows[31] = Bar(b.time, D(102), D(105), D(102), D(104), b.segment)
    entry = rows[32]
    if mode == "missing_entry":
        rows[32] = Bar(entry.time, entry.o, entry.h, entry.l, entry.c, 1)
    elif mode == "censored":
        rows[32] = Bar(entry.time, D(103), D(104), D(99), D(103), 0)
        rows[33:] = [Bar(x.time, x.o, x.h, x.l, x.c, 1) for x in rows[33:]]
    else:
        rows[32] = Bar(entry.time, D(97), D(114), D(97), D(100), 0)
    cohort = research(rows)["cohorts"]["development"]
    yes = cohort["confirmation_three_candle_fvg_census"]["states"][
        "SAME_DIRECTION_THREE_CANDLE_FVG"]
    assert yes["confirmed_signals"] == 1
    assert yes["observed_outcomes"] == 0
    assert yes["confirmed_signals_without_observable_entry"] == int(
        mode == "missing_entry")
    assert yes["invalid_entry_stop_or_target_geometry"] == int(mode == "invalid")
    assert yes["censored_entered_outcomes"] == int(mode == "censored")
    assert yes["entered_positions"] == int(mode == "censored")
    assert all(x["mean_net_r"] is None for x in yes["observed_only_cost_scenarios"])


def test_confirmation_fvg_default_and_empty_cohort_do_not_invent_performance():
    result = research(synthetic_bars())
    dev = result["cohorts"]["development"]
    states = dev["confirmation_three_candle_fvg_census"]["states"]
    assert states["SAME_DIRECTION_THREE_CANDLE_FVG"]["confirmed_signals"] == 0
    assert states["NO_SAME_DIRECTION_THREE_CANDLE_FVG"]["confirmed_signals"] == 1
    for i, case in enumerate(dev["cost_scenarios"]):
        total = sum(
            (D(cell["observed_only_cost_scenarios"][i]["mean_net_r"]) *
             cell["observed_outcomes"]
             for cell in states.values() if cell["observed_outcomes"]), D(0))
        assert total == D(case["sum_net_r"])
    later = result["cohorts"]["exploratory_later"]
    for cell in later["confirmation_three_candle_fvg_census"]["states"].values():
        assert cell["confirmed_signals"] == cell["entered_positions"] == 0
        assert all(x["mean_net_r"] is None for x in cell["observed_only_cost_scenarios"])


@pytest.mark.parametrize("side", ["long", "short"])
@pytest.mark.parametrize("boundary", ["break", "equal", "no_break"])
def test_confirmation_prior_range_break_strict_causal_census(side, boundary):
    rows = synthetic_bars()
    if side == "long":
        # Prior high 101/102/104; confirmation close 102, sweep high 101.
        high = {"break": 101, "equal": 102, "no_break": 104}[boundary]
        b = rows[29]
        rows[29] = Bar(b.time, D(100), D(high), D(99), D(100), b.segment)
    else:
        # Prior low 99/96/94; confirmation close 96, sweep low 99.
        low = {"break": 99, "equal": 96, "no_break": 94}[boundary]
        b = rows[29]
        rows[29] = Bar(b.time, D(100), D(101), D(low), D(100), b.segment)
        for index, values in (
            (30, (100, 102, 99, 100)),
            (31, (98, 98, 95, 96)),
            (32, (97, 103, 90, 95)),
        ):
            b = rows[index]
            rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    result = research(rows)
    cohort = result["cohorts"]["development"]
    states = cohort["confirmation_prior_range_break_census"]["states"]
    yes = states["CONFIRMATION_CLOSE_BREAKS_PRIOR_RANGE"]
    no = states["NO_CONFIRMATION_CLOSE_BREAK_OF_PRIOR_RANGE"]
    assert cohort["confirmed_signals"] == cohort["entered_positions"] == 1
    assert cohort["observed_outcomes"] == 1
    assert yes["confirmed_signals"] == int(boundary == "break")
    assert no["confirmed_signals"] == int(boundary != "break")
    selected = yes if boundary == "break" else no
    assert selected["entered_positions"] == selected["observed_outcomes"] == 1
    for i, case in enumerate(selected["observed_only_cost_scenarios"]):
        assert case["mean_net_r"] == cohort["cost_scenarios"][i]["mean_net_r"]
    assert result["may_execute_order"] is False


@pytest.mark.parametrize("mode", ["missing_entry", "censored", "invalid"])
def test_prior_range_break_retains_unobserved_and_invalid_signals(mode):
    rows = synthetic_bars()
    b = rows[32]
    if mode == "missing_entry":
        rows[32] = Bar(b.time, b.o, b.h, b.l, b.c, 1)
    elif mode == "censored":
        rows[32] = Bar(b.time, D(103), D(104), D(99), D(103), 0)
        rows[33:] = [Bar(x.time, x.o, x.h, x.l, x.c, 1) for x in rows[33:]]
    else:
        rows[32] = Bar(b.time, D(97), D(114), D(97), D(100), 0)
    cohort = research(rows)["cohorts"]["development"]
    yes = cohort["confirmation_prior_range_break_census"]["states"][
        "CONFIRMATION_CLOSE_BREAKS_PRIOR_RANGE"]
    assert yes["confirmed_signals"] == 1
    assert yes["observed_outcomes"] == 0
    assert yes["confirmed_signals_without_observable_entry"] == int(
        mode == "missing_entry")
    assert yes["invalid_entry_stop_or_target_geometry"] == int(mode == "invalid")
    assert yes["censored_entered_outcomes"] == int(mode == "censored")
    assert yes["entered_positions"] == int(mode == "censored")
    assert all(x["mean_net_r"] is None for x in yes["observed_only_cost_scenarios"])


def test_prior_range_break_empty_later_cohort_no_fabricated_returns():
    result = research(synthetic_bars())
    later = result["cohorts"]["exploratory_later"]
    states = later["confirmation_prior_range_break_census"]["states"]
    assert sum(s["confirmed_signals"] for s in states.values()) == 0
    assert all(s["entered_positions"] == s["observed_outcomes"] == 0
               for s in states.values())
    assert all(c["mean_net_r"] is None for s in states.values()
               for c in s["observed_only_cost_scenarios"])
