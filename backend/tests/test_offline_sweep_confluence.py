"""Joint FVG/range-break/body proxy census: synthetic-only regression tests."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from app.offline_sweep_probe import CONFLUENCE_STATES, Bar, research
def synthetic_bars():
    t = datetime(2025, 1, 1)
    rows = [Bar(t + timedelta(minutes=15*i), D(100), D(101), D(99), D(100), 0)
            for i in range(200)]
    rows[30] = Bar(rows[30].time, D(100), D(101), D(98), D(100), 0)
    rows[31] = Bar(rows[31].time, D(100), D(103), D(99), D(102), 0)
    rows[32] = Bar(rows[32].time, D(103), D(114), D(97), D(100), 0)
    return rows


def test_joint_census_is_exhaustive_and_matches_all_marginals():
    report = research(synthetic_bars())
    assert len(CONFLUENCE_STATES) == 8
    assert len(set(CONFLUENCE_STATES)) == 8
    for cohort in report["cohorts"].values():
        joint = cohort["confirmation_fvg_mss_displacement_joint_census"]["states"]
        assert set(joint) == set(CONFLUENCE_STATES)
        fields = (
            ("confirmed_signals", "confirmed_signals"),
            ("entered_positions", "entered_positions"),
            ("observed_outcomes", "observed_outcomes"),
            ("censored_entered_outcomes", "censored_due_to_gaps_or_boundaries"),
            ("confirmed_signals_without_observable_entry",
             "confirmed_signals_without_observable_entry"),
            ("invalid_entry_stop_or_target_geometry",
             "invalid_entry_stop_or_target_geometry"),
        )
        for joint_field, cohort_field in fields:
            assert sum(v[joint_field] for v in joint.values()) == cohort[cohort_field]
        for bit, marginal, positive in (
            (0, "confirmation_three_candle_fvg_census",
             "SAME_DIRECTION_THREE_CANDLE_FVG"),
            (1, "confirmation_prior_range_break_census",
             "CONFIRMATION_CLOSE_BREAKS_PRIOR_RANGE"),
            (2, "confirmation_body_displacement_census",
             "DIRECTIONAL_BODY_GTE_PRIOR_MEDIAN_RANGE"),
        ):
            # All 8 joint categories partition each of the three marginal tables.
            cells = list(cohort[marginal]["states"].values())
            assert sum(v["confirmed_signals"] for v in cells) == cohort["confirmed_signals"]
            assert sum(v["observed_outcomes"] for v in cells) == cohort["observed_outcomes"]
        for i, bps in enumerate((0, 5, 10, 20)):
            total = sum(
                D(v["observed_only_cost_scenarios"][i]["mean_net_r"]) *
                v["observed_outcomes"] for v in joint.values()
                if v["observed_outcomes"]
            )
            assert total == D(cohort["cost_scenarios"][i]["sum_net_r"])
            assert all(v["observed_only_cost_scenarios"][i]["additional_round_trip_bps"]
                       == bps for v in joint.values())


def test_joint_state_is_fixed_at_confirmation_not_by_future_exit():
    rows = synthetic_bars()
    first = research(rows)["cohorts"]["development"]
    key = "FVG0_MSS1_DISP1"
    assert first["confirmation_fvg_mss_displacement_joint_census"]["states"][key][
        "confirmed_signals"] == 1
    # Alter the future entry bar's high/low and hence stop/target outcome.
    # The prior completed confirmation state must not be rewritten.
    b = rows[32]
    rows[32] = Bar(b.time, b.o, D(104), D(102), D(103), b.segment)
    second = research(rows)["cohorts"]["development"]
    assert second["confirmation_fvg_mss_displacement_joint_census"]["states"][key][
        "confirmed_signals"] == 1
    assert not research(rows)["may_execute_order"]


def test_joint_empty_cohort_has_no_fabricated_performance():
    cohort = research(synthetic_bars())["cohorts"]["exploratory_later"]
    for cell in cohort["confirmation_fvg_mss_displacement_joint_census"]["states"].values():
        assert cell["confirmed_signals"] == 0
        assert cell["observed_outcomes"] == 0
        assert all(case["mean_net_r"] is None
                   for case in cell["observed_only_cost_scenarios"])
