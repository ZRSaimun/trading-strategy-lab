"""Synthetic tests only; never depend on proprietary archive bytes."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zipfile import ZipFile
import pytest
from app.offline_sweep_probe import Bar, read_archive, research


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
    if expected is not None:
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
