"""Synthetic-only pseudo-settlement drawdown regression tests."""
from copy import deepcopy
from decimal import Decimal
from itertools import product

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_capacity_drawdown import (_maximum_drawdown,
                                          _maximum_drawdown_with_window,
                                          _terminal_drawdown,
                                          _underwater_event_burden,
                                          _first_pseudo_recovery_event,
                                          _first_pseudo_loss_barrier_event,
                                          _longest_strict_negative_streak,
                                          _strict_sign_count_envelope,
                                           _zero_cost_winner_erosion,
                                          _worst_fixed_booking_window,
                                          _worst_quartile_mean_envelope,
                                          _chronological_quartile_net_r_envelope,
                                          _worst_single_deletion_mean_envelope,
                                          _validated_cost_trajectory,
                                          audit_frozen_capacity_drawdown)
from test_frozen_capacity_week_fragility import CUTOFF, sample, move


def run(manifest, paths, **kwargs):
    return audit_frozen_capacity_drawdown(
        manifest, paths, kwargs.pop("digest", fingerprint_population_manifest(manifest)),
        kwargs.pop("cutoff", CUTOFF), kwargs.pop("embargo", 1440), **kwargs,
    )


def test_exact_drawdown_includes_initial_zero_peak():
    assert _maximum_drawdown([Decimal("-1"), Decimal("-2"), Decimal("3")]) == 3
    assert _maximum_drawdown([Decimal("2"), Decimal("-3"), Decimal("-1")]) == 4
    assert _maximum_drawdown([Decimal("1"), Decimal("2")]) == 0



def test_drawdown_window_uses_earliest_peak_and_trough_ties():
    assert _maximum_drawdown_with_window([Decimal("2"), Decimal("-1"),
                                          Decimal("1"), Decimal("-1")]) == (Decimal("1"), 1, 2)
    assert _maximum_drawdown_with_window([Decimal("-2"), Decimal("3"),
                                          Decimal("-2")]) == (Decimal("2"), 0, 1)
    assert _maximum_drawdown_with_window([Decimal("1"), Decimal("2")]) == (Decimal(0), 0, 0)
    assert _maximum_drawdown_with_window([]) == (Decimal(0), 0, 0)


def test_exhaustive_drawdown_windows_match_independent_quadratic_oracle():
    # 3,125 complete five-event histories, including flat/negative/equal peaks.
    for sequence in product((-2, -1, 0, 1, 2), repeat=5):
        increments = [Decimal(x) for x in sequence]
        equity = [Decimal(0)]
        for increment in increments:
            equity.append(equity[-1] + increment)
        expected = (Decimal(0), 0, 0)
        for trough in range(1, len(equity)):
            for peak in range(trough):
                loss = equity[peak] - equity[trough]
                if loss > expected[0]:
                    expected = (loss, peak, trough)
        assert _maximum_drawdown_with_window(increments) == expected
        assert _maximum_drawdown(increments) == expected[0]
        assert _terminal_drawdown(increments) == max(
            previous - equity[-1] for previous in equity
        )
        assert _terminal_drawdown(increments) <= expected[0]
        recovery = next(
            (event for event in range(expected[2] + 1, len(equity))
             if equity[event] >= equity[expected[1]]),
            None,
        ) if expected[0] > 0 else None
        assert _first_pseudo_recovery_event(increments, *expected[1:], expected[0]) == recovery


def test_holdout_drawdown_window_counts_booked_events_not_broker_fills():
    manifest, paths = sample()
    report = run(manifest, paths)
    scenario = report["cost_scenarios"][0]
    assert scenario["holdout_pseudo_settlement_maximum_max_drawdown_peak_event"] == 0
    assert scenario["holdout_pseudo_settlement_maximum_max_drawdown_trough_event"] == 36
    assert scenario["training_pseudo_settlement_maximum_max_drawdown_peak_event"] == 0
    assert scenario["training_pseudo_settlement_maximum_max_drawdown_trough_event"] == 0



def test_report_preserves_distinct_optimistic_and_pessimistic_peak_events():
    # First holdout opportunity is intrabar ambiguous: the upper return
    # reaches the target and creates a peak at booking event 1; the lower
    # return touches the stop and leaves the peak at event zero. Previously
    # the optimistic peak was written under the maximum key and overwritten.
    manifest, paths = sample()
    paths[36]["bars"][0].update(high="103", low="98", close="100")
    report = run(manifest, paths)
    for scenario in report["cost_scenarios"]:
        assert scenario["holdout_pseudo_settlement_minimum_max_drawdown_peak_event"] == 1
        assert scenario["holdout_pseudo_settlement_maximum_max_drawdown_peak_event"] == 0
        assert scenario["holdout_pseudo_settlement_minimum_max_drawdown_trough_event"] == 36
        assert scenario["holdout_pseudo_settlement_maximum_max_drawdown_trough_event"] == 36
        assert (
            Decimal(scenario["holdout_pseudo_settlement_minimum_max_drawdown_pct_initial"])
            <= Decimal(scenario["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"])
        )
        assert scenario["training_pseudo_settlement_minimum_max_drawdown_peak_event"] == 0
        assert scenario["training_pseudo_settlement_maximum_max_drawdown_peak_event"] == 0


def test_terminal_underwater_differs_from_historical_maximum_drawdown():
    seq = [Decimal("2"), Decimal("-3"), Decimal("3"), Decimal("-1")]
    assert _maximum_drawdown(seq) == 3
    assert _terminal_drawdown(seq) == 1
    assert _terminal_drawdown([Decimal("1"), Decimal("2")]) == 0
    assert _terminal_drawdown([Decimal("-1"), Decimal("-2")]) == 3



def test_underwater_burden_counts_booking_events_not_negative_trades():
    d = Decimal
    assert _underwater_event_burden([]) == (0, 0)
    assert _underwater_event_burden([d("1"), d("2"), d("0")]) == (0, 0)
    assert _underwater_event_burden([d("2"), d("-1"), d("0"), d("1")]) == (2, 2)
    assert _longest_strict_negative_streak(
        [d("2"), d("-1"), d("0"), d("1")]) == 1
    assert _underwater_event_burden(
        [d("2"), d("-1"), d("-1"), d("2"), d("-2"), d("-1"), d("4")]
    ) == (4, 2)
    assert _underwater_event_burden([d("-1"), d("-1"), d("-1")]) == (3, 3)


def test_underwater_burden_matches_independent_exhaustive_interval_oracle():
    # 340 distinct interval populations, all integer outcomes in each,
    # independently compute each prefix equity and its preceding maximum.
    # Exact lower/upper endpoints must bound both total and longest duration.
    choices = ((-2, -1), (-1, 1), (0, 0), (1, 2))
    populations = 0
    for length in range(1, 5):
        for intervals in product(choices, repeat=length):
            lower = [Decimal(a) for a, _ in intervals]
            upper = [Decimal(b) for _, b in intervals]
            actual = []
            for outcomes in product(*[range(a, b + 1) for a, b in intervals]):
                equity = [Decimal(0)]
                for value in outcomes:
                    equity.append(equity[-1] + Decimal(value))
                underwater = [
                    equity[i] < max(equity[:i + 1])
                    for i in range(1, len(equity))
                ]
                total = sum(underwater)
                streak = longest = 0
                for below_peak in underwater:
                    streak = streak + 1 if below_peak else 0
                    longest = max(longest, streak)
                actual.append((total, longest))
            assert _underwater_event_burden(upper) == (
                min(x[0] for x in actual), min(x[1] for x in actual))
            assert _underwater_event_burden(lower) == (
                max(x[0] for x in actual), max(x[1] for x in actual))
            populations += 1
    assert populations == 340


def test_full_report_underwater_event_bounds_preserve_frozen_cohorts():
    manifest, paths = sample()
    report = run(manifest, paths)
    for scenario in report["cost_scenarios"]:
        for label in ("training", "holdout"):
            n = report["admission_counts"][f"{label}_admitted"]
            prefix = f"{label}_pseudo_settlement_"
            minimum_total = scenario[prefix + "minimum_total_underwater_events"]
            maximum_total = scenario[prefix + "maximum_total_underwater_events"]
            minimum_streak = scenario[prefix + "minimum_longest_underwater_event_streak"]
            maximum_streak = scenario[prefix + "maximum_longest_underwater_event_streak"]
            assert 0 <= minimum_streak <= minimum_total <= maximum_total <= n
            assert minimum_streak <= maximum_streak <= maximum_total
    zero = report["cost_scenarios"][0]
    assert zero["training_pseudo_settlement_minimum_total_underwater_events"] == 0
    assert zero["holdout_pseudo_settlement_maximum_total_underwater_events"] == 36
    assert zero["holdout_pseudo_settlement_maximum_longest_underwater_event_streak"] == 36
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False


def test_pseudo_recovery_event_is_not_actual_fill_time():
    assert _first_pseudo_recovery_event(
        [Decimal("2"), Decimal("-3"), Decimal("3")], 1, 2, Decimal("3")
    ) == 3
    assert _first_pseudo_recovery_event(
        [Decimal("2"), Decimal("-3"), Decimal("1")], 1, 2, Decimal("3")
    ) is None
    assert _first_pseudo_recovery_event(
        [Decimal("1"), Decimal("2")], 0, 0, Decimal(0)
    ) is None
    with pytest.raises(ValueError, match="window"):
        _first_pseudo_recovery_event([Decimal("-1")], 1, 0, Decimal("1"))


def test_report_recovery_is_explicitly_null_when_never_recovered():
    manifest, paths = sample()
    report = run(manifest, paths)
    scenario = report["cost_scenarios"][0]
    assert scenario["holdout_pseudo_settlement_maximum_max_drawdown_recovery_event"] is None
    assert scenario["holdout_pseudo_settlement_minimum_max_drawdown_recovery_event"] is None
    assert scenario["training_pseudo_settlement_maximum_max_drawdown_recovery_event"] is None


def test_complete_frozen_cohorts_and_losses():
    m, p = sample()
    r = run(m, p)
    assert r["status"] == "DESCRIPTIVE_FIXED_HORIZON_DRAWDOWN_ENVELOPE_ONLY"
    assert r["eligible_signals"] == 72
    assert r["admission_counts"]["holdout_admitted"] == 36
    s = r["cost_scenarios"][0]
    assert Decimal(s["training_pseudo_settlement_maximum_max_drawdown_pct_initial"]) == 0
    assert Decimal(s["holdout_pseudo_settlement_minimum_max_drawdown_pct_initial"]) == 18
    assert Decimal(s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"]) == 18
    assert Decimal(s["holdout_pseudo_settlement_final_lower_pct_initial"]) == -18
    assert Decimal(s["holdout_pseudo_settlement_minimum_terminal_underwater_pct_initial"]) == 18
    assert Decimal(s["holdout_pseudo_settlement_maximum_terminal_underwater_pct_initial"]) == 18
    assert Decimal(s["training_pseudo_settlement_maximum_terminal_underwater_pct_initial"]) == 0
    assert r["verified_profitability"] is False
    assert r["may_execute_order"] is False


def test_all_cost_scenarios_and_worsening_drawdown():
    m, p = sample()
    r = run(m, p)
    assert [s["additional_round_trip_bps"] for s in r["cost_scenarios"]] == [0, 5, 10, 20]
    d = [Decimal(s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"])
         for s in r["cost_scenarios"]]
    assert d == sorted(d)


def test_ambiguous_path_keeps_nonzero_envelope():
    m, p = sample()
    p[40]["bars"][0].update(high="103", low="98", close="100")
    s = run(m, p)["cost_scenarios"][0]
    assert Decimal(s["holdout_pseudo_settlement_minimum_max_drawdown_pct_initial"]) < Decimal(
        s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"])


def test_capacity_rejection_is_counted_not_selected_by_winner():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p)
    assert r["admission_counts"]["holdout_admitted"] == 35
    assert r["admission_counts"]["holdout_unadmitted"] == 1
    assert r["cost_scenarios"][0]["holdout_pseudo_settlement_final_lower_pct_initial"] == "-17.5"


def test_early_target_does_not_release_capacity():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    p[36]["bars"][0].update(high="103", close="100")
    assert run(m, p)["admission_counts"]["holdout_unadmitted"] == 1


def test_input_order_does_not_change_results_or_mutate_data():
    m, p = sample()
    original = deepcopy((m, p))
    expected = run(m, p)
    assert (m, p) == original
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == expected


def test_incomplete_path_withholds_all_drawdown_statistics():
    m, p = sample()
    p[40]["bars"] = []
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []


def test_declared_exclusions_withhold():
    m, p = sample()
    m["excluded_signals"].append(dict(path_id="excluded", signal_at=CUTOFF - 37 * 7 * 86400,
                                      reason="PRE_SIGNAL_DATA_GAP"))
    assert run(m, p)["cost_scenarios"] == []


def test_insufficient_admitted_holdout_withholds():
    m, p = sample()
    for i in range(37, 49):
        move(m, p, i, CUTOFF + (i - 36) * 60)
    assert run(m, p)["cost_scenarios"] == []


def test_invalid_digest_fails_closed():
    m, p = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


def test_bad_policy_and_cutoff_fail_closed():
    m, p = sample()
    with pytest.raises(ValueError):
        run(m, p, max_positions=0)
    with pytest.raises(ValueError):
        run(m, p, cutoff=CUTOFF + 60)
    with pytest.raises(ValueError):
        run(m, p, embargo=0)


def test_risk_bps_scale_pseudo_equity_not_broker_margin():
    m, p = sample()
    s = run(m, p, per_position_risk_bps=50)["cost_scenarios"][0]
    assert Decimal(s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"]) == 9


def test_pseudo_loss_barrier_first_touch_and_no_touch():
    d = Decimal
    assert _first_pseudo_loss_barrier_event([d("-1"), d("-1")], d(1), d(2)) == 2
    assert _first_pseudo_loss_barrier_event([d("-2"), d("3")], d(1), d(2)) == 1
    assert _first_pseudo_loss_barrier_event([d("2"), d("-2")], d(1), d(1)) is None
    assert _first_pseudo_loss_barrier_event([], d(1), d(1)) is None
    assert _first_pseudo_loss_barrier_event([d("-1")], d("0.5"), d("0.5")) == 1
    with pytest.raises(ValueError, match="Positive"):
        _first_pseudo_loss_barrier_event([d("-1")], d(0), d(1))
    with pytest.raises(ValueError, match="Positive"):
        _first_pseudo_loss_barrier_event([d("-1")], d(1), d(0))


def test_loss_barrier_envelope_matches_independent_all_path_oracle():
    # Enumerate every integer outcome inside each interval. This independent
    # oracle compares earliest *possible* breach and earliest *unavoidable*
    # breach over all complete pseudo-return sequences (no random sampling).
    interval_choices = ((-2, -1), (-1, 1), (0, 0), (1, 2))
    for length in range(1, 5):
        for intervals in product(interval_choices, repeat=length):
            lo = [Decimal(pair[0]) for pair in intervals]
            hi = [Decimal(pair[1]) for pair in intervals]
            paths = product(*[range(a, b + 1) for a, b in intervals])
            histories = []
            for increments in paths:
                running = Decimal(0)
                prefix = []
                for value in increments:
                    running += Decimal(value)
                    prefix.append(running)
                histories.append(prefix)
            for barrier in (Decimal(1), Decimal(2), Decimal(4)):
                firsts = [
                    next((i for i, value in enumerate(history, 1)
                          if value <= -barrier), None)
                    for history in histories
                ]
                actual_possible = _first_pseudo_loss_barrier_event(lo, Decimal(1), barrier)
                actual_unavoidable = _first_pseudo_loss_barrier_event(hi, Decimal(1), barrier)
                observed = [i for i in firsts if i is not None]
                expected_possible = min(observed) if observed else None
                expected_unavoidable = max(observed) if len(observed) == len(firsts) else None
                assert (actual_possible, actual_unavoidable) == (
                    expected_possible, expected_unavoidable)


def test_complete_report_has_both_declared_pseudo_loss_barriers():
    m, p = sample()
    report = run(m, p)
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False
    scenario = report["cost_scenarios"][0]
    holdout = scenario["holdout_pseudo_settlement_loss_barriers"]
    training = scenario["training_pseudo_settlement_loss_barriers"]
    assert [b["threshold_pct_initial"] for b in holdout] == [10, 20]
    assert holdout[0] == {
        "threshold_pct_initial": 10,
        "first_possible_event": 20,
        "first_unavoidable_event": 20,
        "envelope_status": "UNAVOIDABLE_WITHIN_INTERVAL_ENVELOPE",
    }
    assert holdout[1]["envelope_status"] == "NOT_REACHED_WITHIN_INTERVAL_ENVELOPE"
    assert all(b["first_possible_event"] is None for b in training)


def test_interval_ambiguity_keeps_possible_distinct_from_unavoidable():
    # The two endpoints can cross a threshold at different times; this
    # classification must not become a probability or execution decision.
    lo = [Decimal("-2"), Decimal("-1"), Decimal("2")]
    hi = [Decimal("-1"), Decimal("1"), Decimal("2")]
    assert _first_pseudo_loss_barrier_event(lo, Decimal(1), Decimal(2)) == 1
    assert _first_pseudo_loss_barrier_event(hi, Decimal(1), Decimal(2)) is None


def test_strict_negative_streak_zero_and_positive_break_runs():
    d = Decimal
    assert _longest_strict_negative_streak([]) == 0
    assert _longest_strict_negative_streak([d("0"), d("1")]) == 0
    assert _longest_strict_negative_streak(
        [d("-1"), d("-2"), d("0"), d("-3"), d("1"), d("-4")]
    ) == 2
    assert _longest_strict_negative_streak([d("-0.0001")] * 4) == 4


def test_strict_negative_streak_interval_bounds_against_exhaustive_oracle():
    # Independent quadratic oracle checks every integer-valued path across
    # 4,680 possible histories, including zero and sign-spanning intervals.
    choices = ((-2, -1), (-1, 1), (0, 0), (1, 2))
    checked = 0
    for length in range(1, 5):
        for intervals in product(choices, repeat=length):
            observed = []
            for values in product(*(range(a, b + 1) for a, b in intervals)):
                expected = max((
                    end - start
                    for start in range(length)
                    for end in range(start + 1, length + 1)
                    if all(value < 0 for value in values[start:end])
                ), default=0)
                observed.append(expected)
                checked += 1
            assert min(observed) == _longest_strict_negative_streak(
                [Decimal(hi) for _, hi in intervals]
            )
            assert max(observed) == _longest_strict_negative_streak(
                [Decimal(lo) for lo, _ in intervals]
            )
    assert checked == 4680


def test_report_strict_negative_streak_keeps_all_admitted_losses():
    manifest, paths = sample()
    report = run(manifest, paths)
    scenario = report["cost_scenarios"][0]
    assert scenario["holdout_pseudo_settlement_minimum_longest_strict_negative_path_streak"] == 36
    assert scenario["holdout_pseudo_settlement_maximum_longest_strict_negative_path_streak"] == 36
    assert scenario["training_pseudo_settlement_minimum_longest_strict_negative_path_streak"] == 0
    assert scenario["training_pseudo_settlement_maximum_longest_strict_negative_path_streak"] == 0
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False


def test_ambiguous_outcomes_preserve_negative_streak_interval():
    manifest, paths = sample()
    paths[40]["bars"][0].update(high="103", low="98", close="100")
    scenario = run(manifest, paths)["cost_scenarios"][0]
    lower = scenario["holdout_pseudo_settlement_minimum_longest_strict_negative_path_streak"]
    upper = scenario["holdout_pseudo_settlement_maximum_longest_strict_negative_path_streak"]
    assert 0 <= lower <= upper <= 36


def test_strict_sign_census_zero_is_neither_win_nor_loss():
    d = Decimal
    assert _strict_sign_count_envelope(
        [d("-2"), d("0"), d("-1"), d("2")],
        [d("1"), d("0"), d("-0.1"), d("2")],
    ) == dict(
        admitted_paths=4,
        guaranteed_strict_positive=1,
        possible_strict_positive=2,
        guaranteed_strict_negative=1,
        possible_strict_negative=2,
        guaranteed_exact_zero=1,
        possible_exact_zero=2,
    )
    assert _strict_sign_count_envelope([], [])["admitted_paths"] == 0
    with pytest.raises(ValueError, match="intervals"):
        _strict_sign_count_envelope([d("1")], [d("0")])
    with pytest.raises(ValueError, match="intervals"):
        _strict_sign_count_envelope([d("1")], [])


def test_strict_sign_census_matches_exhaustive_independent_integer_oracle():
    # All 4,680 complete interval-compatible synthetic histories across
    # lengths 1..4 are independently counted for all three strict sign classes.
    # An interval spanning zero is never retrospectively forced to a winner.
    choices = ((-2, -1), (-1, 1), (0, 0), (1, 2))
    checked_histories = 0
    for length in range(1, 5):
        for intervals in product(choices, repeat=length):
            actual = _strict_sign_count_envelope(
                [Decimal(a) for a, _ in intervals],
                [Decimal(b) for _, b in intervals],
            )
            observed = []
            for values in product(*(range(a, b + 1) for a, b in intervals)):
                observed.append((
                    sum(value > 0 for value in values),
                    sum(value < 0 for value in values),
                    sum(value == 0 for value in values),
                ))
                checked_histories += 1
            for name, index in (("strict_positive", 0),
                                ("strict_negative", 1),
                                ("exact_zero", 2)):
                assert actual[f"guaranteed_{name}"] == min(row[index] for row in observed)
                assert actual[f"possible_{name}"] == max(row[index] for row in observed)
    assert checked_histories == 4680


def test_complete_frozen_report_includes_cost_sensitive_sign_census():
    m, p = sample()
    r = run(m, p)
    assert r["verified_profitability"] is False
    assert r["may_execute_order"] is False
    for label in ("training", "holdout"):
        admitted = r["admission_counts"][f"{label}_admitted"]
        previous = None
        for scenario in r["cost_scenarios"]:
            counts = scenario[f"{label}_pseudo_settlement_strict_sign_census"]
            assert counts["admitted_paths"] == admitted
            assert 0 <= counts["guaranteed_strict_positive"] <= counts["possible_strict_positive"] <= admitted
            assert 0 <= counts["guaranteed_strict_negative"] <= counts["possible_strict_negative"] <= admitted
            assert 0 <= counts["guaranteed_exact_zero"] <= counts["possible_exact_zero"] <= admitted
            if previous is not None:
                assert counts["possible_strict_positive"] <= previous["possible_strict_positive"]
                assert counts["guaranteed_strict_positive"] <= previous["guaranteed_strict_positive"]
                assert counts["possible_strict_negative"] >= previous["possible_strict_negative"]
                assert counts["guaranteed_strict_negative"] >= previous["guaranteed_strict_negative"]
            previous = counts


def test_ambiguous_outcome_retains_possible_signs_not_fake_win_rate():
    m, p = sample()
    p[40]["bars"][0].update(high="103", low="98", close="100")
    s = run(m, p)["cost_scenarios"][0]
    counts = s["holdout_pseudo_settlement_strict_sign_census"]
    assert counts["admitted_paths"] == 36
    assert counts["guaranteed_strict_positive"] <= counts["possible_strict_positive"]
    assert counts["guaranteed_strict_negative"] <= counts["possible_strict_negative"]


def test_rejected_capacity_paths_have_separate_complete_sign_census():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p)
    assert r["admission_counts"]["holdout_unadmitted"] == 1
    for scenario in r["cost_scenarios"]:
        admitted = scenario["holdout_pseudo_settlement_strict_sign_census"]
        rejected = scenario["holdout_pseudo_settlement_unadmitted_strict_sign_census"]
        assert admitted["admitted_paths"] == 35
        assert rejected["unadmitted_paths"] == 1
        assert rejected["guaranteed_strict_negative"] == 1
        assert rejected["possible_strict_positive"] == 0
        assert scenario["training_pseudo_settlement_unadmitted_strict_sign_census"] == {
            "unadmitted_paths": 0,
            "guaranteed_strict_positive": 0, "possible_strict_positive": 0,
            "guaranteed_strict_negative": 0, "possible_strict_negative": 0,
            "guaranteed_exact_zero": 0, "possible_exact_zero": 0,
        }


def test_rejected_ambiguous_path_preserves_both_possible_signs():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    p[37]["bars"][0].update(high="103", low="98", close="100")
    s = run(m, p)["cost_scenarios"][0]
    rejected = s["holdout_pseudo_settlement_unadmitted_strict_sign_census"]
    assert rejected["unadmitted_paths"] == 1
    assert rejected["possible_strict_positive"] == 1
    assert rejected["possible_strict_negative"] == 1
    assert rejected["guaranteed_strict_positive"] == 0
    assert rejected["guaranteed_strict_negative"] == 0
    assert s["holdout_pseudo_settlement_strict_sign_census"]["admitted_paths"] == 35


def test_rejected_outcome_changes_do_not_retroactively_change_admissions():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    baseline = run(m, p)
    for bar in p[37]["bars"]:
        bar["close"] = "100.5"
    changed = run(m, p)
    assert changed["admission_counts"] == baseline["admission_counts"]
    assert all(
        a["holdout_pseudo_settlement_strict_sign_census"]
        == b["holdout_pseudo_settlement_strict_sign_census"]
        for a, b in zip(baseline["cost_scenarios"], changed["cost_scenarios"])
    )
    assert changed["cost_scenarios"][0][
        "holdout_pseudo_settlement_unadmitted_strict_sign_census"
    ]["guaranteed_strict_positive"] == 1


def test_worst_quartile_net_r_exact_values_and_fail_closed():
    d = Decimal
    result = _worst_quartile_mean_envelope(
        [d("-3"), d("-1"), d("0"), d("1"), d("2"), d("3"), d("4"), d("5")],
        [d("-2"), d("0"), d("1"), d("2"), d("3"), d("4"), d("5"), d("6")],
    )
    assert result == {
        "admitted_paths": 8, "worst_quartile_paths": 2,
        "minimum_worst_quartile_mean_net_r": "-2",
        "maximum_worst_quartile_mean_net_r": "-1",
    }
    with pytest.raises(ValueError, match="quartile"):
        _worst_quartile_mean_envelope([], [])
    with pytest.raises(ValueError, match="quartile"):
        _worst_quartile_mean_envelope([d("1")], [d("0")])
    with pytest.raises(ValueError, match="quartile"):
        _worst_quartile_mean_envelope([d("0")], [])


def test_worst_quartile_bounds_match_independent_exhaustive_oracle():
    # Enumerate every integer outcome of 4,680 short interval histories;
    # extend to 5/6 events so the bottom quartile contains two outcomes.
    interval_sets = (
        ((-2, -1), (-1, 1), (0, 0), (1, 2)),
        ((-2, -1), (0, 1)),
    )
    checked = 0
    for choices, lengths in zip(interval_sets, ((1, 2, 3, 4), (5, 6))):
        for length in lengths:
            for intervals in product(choices, repeat=length):
                actual = _worst_quartile_mean_envelope(
                    [Decimal(a) for a, _ in intervals],
                    [Decimal(b) for _, b in intervals],
                )
                k = (length + 3) // 4
                observed = []
                for values in product(*(range(a, b + 1) for a, b in intervals)):
                    observed.append(
                        sum(sorted(map(Decimal, values))[:k], Decimal(0)) / k
                    )
                    checked += 1
                assert actual["admitted_paths"] == length
                assert actual["worst_quartile_paths"] == k
                assert Decimal(actual["minimum_worst_quartile_mean_net_r"]) == min(observed)
                assert Decimal(actual["maximum_worst_quartile_mean_net_r"]) == max(observed)
    assert checked == 9800


def test_admitted_tail_envelope_is_cost_monotone_and_capacity_frozen():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    before = run(m, p)
    assert before["admission_counts"]["holdout_unadmitted"] == 1
    for cohort in ("training", "holdout"):
        previous = None
        for scenario in before["cost_scenarios"]:
            tail = scenario[f"{cohort}_pseudo_settlement_worst_quartile_net_r"]
            assert tail["admitted_paths"] == before["admission_counts"][f"{cohort}_admitted"]
            assert tail["worst_quartile_paths"] == (tail["admitted_paths"] + 3) // 4
            assert Decimal(tail["minimum_worst_quartile_mean_net_r"]) <= Decimal(
                tail["maximum_worst_quartile_mean_net_r"])
            if previous:
                for bound in ("minimum_worst_quartile_mean_net_r",
                              "maximum_worst_quartile_mean_net_r"):
                    assert Decimal(tail[bound]) <= Decimal(previous[bound])
            previous = tail
    # A changed rejected result must not alter admitted tail measurements.
    for bar in p[37]["bars"]:
        bar["close"] = "100.5"
    after = run(m, p)
    assert before["admission_counts"] == after["admission_counts"]
    for old, new in zip(before["cost_scenarios"], after["cost_scenarios"]):
        for cohort in ("training", "holdout"):
            key = f"{cohort}_pseudo_settlement_worst_quartile_net_r"
            assert old[key] == new[key]


def test_individual_path_cost_trajectory_is_exact_and_monotone():
    rows = [
        {"additional_round_trip_bps": bps,
         "lower_net_r": lower, "upper_net_r": upper}
        for bps, lower, upper in (
            (0, "-2", "1"), (5, "-2.1", "0.9"),
            (10, "-2.2", "0.8"), (20, "-2.4", "0.6"))
    ]
    assert _validated_cost_trajectory(rows) == (
        (Decimal("-2"), Decimal("1")),
        (Decimal("-2.1"), Decimal("0.9")),
        (Decimal("-2.2"), Decimal("0.8")),
        (Decimal("-2.4"), Decimal("0.6")),
    )
    with pytest.raises(ValueError, match="Incomplete"):
        _validated_cost_trajectory(rows[:-1])
    with pytest.raises(ValueError, match="identity"):
        _validated_cost_trajectory([dict(r, additional_round_trip_bps=True)
                                    if i == 1 else r for i, r in enumerate(rows)])
    with pytest.raises(ValueError, match="Inverted"):
        _validated_cost_trajectory([dict(r, lower_net_r="2")
                                    if i == 2 else r for i, r in enumerate(rows)])
    with pytest.raises(ValueError, match="Nonmonotone"):
        _validated_cost_trajectory([dict(r, lower_net_r="-1.9")
                                    if i == 1 else r for i, r in enumerate(rows)])
    with pytest.raises(ValueError, match="Nonmonotone"):
        _validated_cost_trajectory([dict(r, upper_net_r="1.1")
                                    if i == 1 else r for i, r in enumerate(rows)])


def test_aggregate_cost_erosion_cannot_hide_an_improving_individual_path():
    # Across two paths the *cohort* lower/upper means deteriorate,
    # yet one path's lower return improves as additional cost rises.
    # Aggregate-only checks would miss this corrupt per-path trajectory.
    improving = [
        {"additional_round_trip_bps": bps,
         "lower_net_r": lo, "upper_net_r": hi}
        for bps, lo, hi in (
            (0, "-2", "1"), (5, "-1.9", "0.9"),
            (10, "-2.1", "0.8"), (20, "-2.2", "0.7"))
    ]
    worsening = [
        {"additional_round_trip_bps": bps,
         "lower_net_r": lo, "upper_net_r": hi}
        for bps, lo, hi in (
            (0, "-2", "1"), (5, "-4", "-1"),
            (10, "-5", "-2"), (20, "-6", "-3"))
    ]
    for key in ("lower_net_r", "upper_net_r"):
        sums = [sum((Decimal(rows[i][key]) for rows in (improving, worsening)),
                    Decimal(0)) for i in range(4)]
        assert sums == sorted(sums, reverse=True)
    assert len(_validated_cost_trajectory(worsening)) == 4
    with pytest.raises(ValueError, match="Nonmonotone individual"):
        _validated_cost_trajectory(improving)


def test_full_auditor_rejects_corrupt_path_even_before_cohort_mean(monkeypatch):
    # Upstream capacity totals remain unchanged; only a single audited
    # per-path scenario is corrupted. The new guard must reject it before
    # aggregate reconciliation can obscure the precise integrity failure.
    from app import frozen_capacity_drawdown as module
    original = module.audit_frozen_bracket_population

    def corrupted(manifest, paths, digest):
        report = original(manifest, paths, digest)
        scenarios = report["outcome_audit"]["paths"][0]["cost_scenarios"]
        scenarios[1]["upper_net_r"] = str(
            Decimal(scenarios[0]["upper_net_r"]) + Decimal("0.01")
        )
        return report

    monkeypatch.setattr(module, "audit_frozen_bracket_population", corrupted)
    manifest, paths = sample()
    with pytest.raises(ValueError, match="Nonmonotone individual path"):
        run(manifest, paths)


def test_exact_declared_cost_erosion_rejects_monotone_undercharge():
    # Frozen entry=100, stop=99 -> 1 price unit at risk. The *illustrative*
    # round-trip cost is 0.05 R per 5 bps, not a broker execution quote.
    rows = [
        dict(additional_round_trip_bps=bps,
             lower_net_r=lo, upper_net_r=hi)
        for bps, lo, hi in (
            (0, "-1", "1"), (5, "-1.05", "0.95"),
            (10, "-1.10", "0.90"), (20, "-1.20", "0.80"),
        )
    ]
    assert len(_validated_cost_trajectory(
        rows, frozen_entry="100", frozen_stop="99",
        lower_gross_r="-1", upper_gross_r="1",
    )) == 4
    undercharged = deepcopy(rows)
    undercharged[1]["lower_net_r"] = "-1.01"
    undercharged[1]["upper_net_r"] = "0.99"
    # The old monotonicity-only invariant accepts this counterfeit schedule.
    assert len(_validated_cost_trajectory(undercharged)) == 4
    with pytest.raises(ValueError, match="Incorrect per-path frozen cost erosion"):
        _validated_cost_trajectory(
            undercharged, frozen_entry="100", frozen_stop="99",
            lower_gross_r="-1", upper_gross_r="1",
        )


def test_declared_cost_identity_rejects_missing_and_inverted_gross():
    rows = [
        dict(additional_round_trip_bps=bps,
             lower_net_r="-1", upper_net_r="1")
        for bps in (0, 5, 10, 20)
    ]
    with pytest.raises(ValueError, match="Incomplete per-path frozen cost identity"):
        _validated_cost_trajectory(rows, frozen_entry="100")
    with pytest.raises(ValueError, match="denominator"):
        _validated_cost_trajectory(
            rows, frozen_entry="100", frozen_stop="100",
            lower_gross_r="-1", upper_gross_r="1",
        )
    with pytest.raises(ValueError, match="gross-R"):
        _validated_cost_trajectory(
            rows, frozen_entry="100", frozen_stop="99",
            lower_gross_r="2", upper_gross_r="1",
        )


def test_full_auditor_rejects_monotone_but_false_cost_schedule(monkeypatch):
    # A monotone forged path can be missed by aggregate-only comparisons.
    # The independent frozen bracket + gross-R identity must reject it
    # *before* admitted means are computed or a holdout statistic is reported.
    from app import frozen_capacity_drawdown as module
    original = module.audit_frozen_bracket_population

    def undercharged(manifest, paths, digest):
        report = original(manifest, paths, digest)
        scenarios = report["outcome_audit"]["paths"][0]["cost_scenarios"]
        for key in ("lower_net_r", "upper_net_r"):
            first = Decimal(scenarios[0][key])
            five = Decimal(scenarios[1][key])
            scenarios[1][key] = str((first + five) / 2)
        assert len(_validated_cost_trajectory(scenarios)) == 4
        return report

    monkeypatch.setattr(module, "audit_frozen_bracket_population", undercharged)
    manifest, paths = sample()
    with pytest.raises(ValueError, match="Incorrect per-path frozen cost erosion"):
        run(manifest, paths)


def test_paired_zero_cost_winner_erosion_exact_and_fail_closed():
    d = Decimal
    result = _zero_cost_winner_erosion(
        [d("1"), d("1"), d("1"), d("-1"), d("0")],
        [d("1"), d("2"), d("2"), d("1"), d("0")],
        [d("-0.1"), d("-0.5"), d("0.1"), d("-2"), d("0")],
        [d("-0.1"), d("0.5"), d("1.1"), d("0"), d("0")],
    )
    assert result == dict(
        evaluated_paths=5, zero_cost_guaranteed_strict_positive=3,
        guaranteed_no_longer_strict_positive=1,
        possible_no_longer_strict_positive=2,
        still_guaranteed_strict_positive=1,
    )
    with pytest.raises(ValueError, match="Mismatched"):
        _zero_cost_winner_erosion([d("1")], [d("1")], [], [])
    with pytest.raises(ValueError, match="nonmonotone"):
        _zero_cost_winner_erosion([d("1")], [d("2")], [d("2")], [d("2")])
    with pytest.raises(ValueError, match="interval"):
        _zero_cost_winner_erosion([d("2")], [d("1")], [d("1")], [d("1")])


def test_paired_erosion_matches_independent_discrete_outcome_oracle():
    # Enumerate possible gross returns before applying a fixed cost decrement.
    d = Decimal
    intervals = [(lo, hi) for lo in range(-2, 3)
                 for hi in range(lo, 3)]
    for lo, hi in intervals:
        for cost in (0, 1, 2, 3):
            observed = _zero_cost_winner_erosion(
                [d(lo)], [d(hi)], [d(lo - cost)], [d(hi - cost)])
            outcomes = list(range(lo, hi + 1))
            baseline = all(x > 0 for x in outcomes)
            possible = baseline and any(x - cost <= 0 for x in outcomes)
            guaranteed = baseline and all(x - cost <= 0 for x in outcomes)
            survive = baseline and all(x - cost > 0 for x in outcomes)
            assert observed["zero_cost_guaranteed_strict_positive"] == int(baseline)
            assert observed["possible_no_longer_strict_positive"] == int(possible)
            assert observed["guaranteed_no_longer_strict_positive"] == int(guaranteed)
            assert observed["still_guaranteed_strict_positive"] == int(survive)


def test_full_report_paired_erosion_covers_admitted_and_rejected_population():
    manifest, paths = sample()
    report = run(manifest, paths)
    for label in ("training", "holdout"):
        for population in ("admitted", "unadmitted"):
            key = f"{label}_pseudo_settlement_{population}_zero_cost_winner_erosion"
            rows = [scenario[key] for scenario in report["cost_scenarios"]]
            expected_size = report["admission_counts"][f"{label}_{population}"]
            assert all(row["evaluated_paths"] == expected_size for row in rows)
            assert all(row["zero_cost_guaranteed_strict_positive"]
                       == rows[0]["zero_cost_guaranteed_strict_positive"] for row in rows)
            assert rows[0]["guaranteed_no_longer_strict_positive"] == 0
            assert rows[0]["possible_no_longer_strict_positive"] == 0
            assert [row["possible_no_longer_strict_positive"] for row in rows] == sorted(
                row["possible_no_longer_strict_positive"] for row in rows)
            assert [row["guaranteed_no_longer_strict_positive"] for row in rows] == sorted(
                row["guaranteed_no_longer_strict_positive"] for row in rows)
            for row in rows:
                assert (row["possible_no_longer_strict_positive"]
                        + row["still_guaranteed_strict_positive"]
                        == row["zero_cost_guaranteed_strict_positive"])
                assert (row["guaranteed_no_longer_strict_positive"]
                        <= row["possible_no_longer_strict_positive"])


def test_continuous_cost_tolerance_is_exact_at_strict_break_even():
    from app.frozen_capacity_drawdown import _baseline_strict_winner_cost_tolerance
    d = Decimal
    population = [(1, 1, "A"), (2, 2, "B"), (3, 3, "C")]
    frozen = {
        "A": {"entry": "100", "stop": "99"},
        "B": {"entry": "200", "stop": "198"},
        "C": {"entry": "100", "stop": "99"},
    }
    trajectories = {
        "A": ((d("0.1"), d("0.3")),),
        "B": ((d("0.2"), d("0.4")),),
        "C": ((d("-0.1"), d("0.9")),),
    }
    report = _baseline_strict_winner_cost_tolerance(population, frozen, trajectories)
    assert report["population_paths"] == 3
    assert report["baseline_guaranteed_strict_positive_paths"] == 2
    assert report["additional_bps_to_erase_guaranteed_positive"] == {
        "minimum": "10.0", "median": "15.0", "maximum": "20.0",
    }
    assert report["additional_bps_to_erase_possible_positive"] == {
        "minimum": "30.0", "median": "35.0", "maximum": "40.0",
    }
    for name in ("A", "B"):
        entry, stop = d(frozen[name]["entry"]), d(frozen[name]["stop"])
        risk = abs(entry - stop)
        for gross, threshold in zip(trajectories[name][0],
                                    (gross * d(10000) * risk / abs(entry)
                                     for gross in trajectories[name][0])):
            for bps in (d(0), d(5), d(10), d(20), d(30), d(40), d(41)):
                net = gross - abs(entry) * bps / d(10000) / risk
                assert (net > 0) == (bps < threshold)


def test_cost_tolerance_empty_winners_and_invalid_brackets():
    from app.frozen_capacity_drawdown import _baseline_strict_winner_cost_tolerance
    population = [(1, 1, "X")]
    frozen = {"X": {"entry": "100", "stop": "99"}}
    no_winner = {"X": ((Decimal("-1"), Decimal("1")),)}
    report = _baseline_strict_winner_cost_tolerance(population, frozen, no_winner)
    assert report["baseline_guaranteed_strict_positive_paths"] == 0
    assert report["additional_bps_to_erase_guaranteed_positive"] == {
        "minimum": None, "median": None, "maximum": None,
    }
    assert report["additional_bps_to_erase_possible_positive"] == {
        "minimum": None, "median": None, "maximum": None,
    }
    with pytest.raises(ValueError, match="denominator"):
        _baseline_strict_winner_cost_tolerance(
            population, {"X": {"entry": "100", "stop": "100"}},
            {"X": ((Decimal("1"), Decimal("2")),)},
        )


def test_full_report_continuous_cost_tolerance_matches_frozen_zero_cost_census():
    manifest, paths = sample()
    report = run(manifest, paths)
    summaries = report["break_even_tolerance"]
    zero = report["cost_scenarios"][0]
    for cohort in ("training", "holdout"):
        for status in ("admitted", "unadmitted"):
            key = f"{cohort}_{status}"
            census_key = f"{cohort}_pseudo_settlement_" + (
                "strict_sign_census" if status == "admitted"
                else "unadmitted_strict_sign_census")
            census = zero[census_key]
            assert summaries[key]["population_paths"] == census[
                "admitted_paths" if status == "admitted" else "unadmitted_paths"]
            assert summaries[key]["baseline_guaranteed_strict_positive_paths"] == (
                census["guaranteed_strict_positive"])
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False


def test_worst_fixed_booking_window_matches_independent_quadratic_oracle():
    # Exhaustive 3,125 five-event histories, including flat and tied minima.
    for sequence in product((-2, -1, 0, 1, 2), repeat=5):
        values = [Decimal(x) for x in sequence]
        for width in (1, 2, 3, 5):
            candidates = [
                (sum(values[start:start + width], Decimal(0)),
                 start, start + width)
                for start in range(len(values) - width + 1)
            ]
            # First occurrence wins ties, independently of rolling algorithm.
            expected = min(candidates, key=lambda item: item[0])
            assert _worst_fixed_booking_window(values, width) == expected


def test_worst_fixed_booking_window_rejects_invalid_widths():
    for width in (0, -1, True, 4, 1.0):
        with pytest.raises(ValueError, match="window size"):
            _worst_fixed_booking_window([Decimal(-1), Decimal(2)], width)


def test_full_report_fixed_window_envelopes_are_causal_and_cost_monotone():
    manifest, paths = sample()
    report = run(manifest, paths)
    for label in ("training", "holdout"):
        key = f"{label}_pseudo_settlement_fixed_window_adverse_sums"
        previous = None
        for scenario in report["cost_scenarios"]:
            windows = scenario[key]
            assert [row["booking_window_paths"] for row in windows] == [5, 10]
            cohort_size = report["admission_counts"][f"{label}_admitted"]
            for row in windows:
                width = row["booking_window_paths"]
                for bound in ("minimum", "maximum"):
                    start = row[f"{bound}_worst_window_start_event"]
                    end = row[f"{bound}_worst_window_end_event"]
                    assert 0 <= start < end <= cohort_size
                    assert end - start == width
                assert (Decimal(row["minimum_worst_window_pct_initial"])
                        <= Decimal(row["maximum_worst_window_pct_initial"]))
            if previous is not None:
                for current, old in zip(windows, previous):
                    for bound in ("minimum", "maximum"):
                        assert (Decimal(current[f"{bound}_worst_window_pct_initial"])
                                <= Decimal(old[f"{bound}_worst_window_pct_initial"]))
            previous = windows
    assert report["source_authenticated"] is False
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False


def test_chronological_quartiles_preserve_fixed_booking_boundaries():
    lower = [Decimal(x) for x in (-4, -3, 1, 2, 3, 4, 5, 6, 7)]
    upper = [x + Decimal(2) for x in lower]
    result = _chronological_quartile_net_r_envelope(lower, upper)
    quartiles = result["quartiles"]
    assert [(q["start_booking_event"], q["end_booking_event"]) for q in quartiles] == [
        (0, 2), (2, 4), (4, 6), (6, 9)]
    assert [q["booked_paths"] for q in quartiles] == [2, 2, 2, 3]
    assert Decimal(quartiles[0]["lower_mean_net_r"]) == Decimal("-3.5")
    assert Decimal(quartiles[0]["upper_mean_net_r"]) == Decimal("-1.5")
    assert result["guaranteed_positive_quartiles"] == 3
    assert result["possible_positive_quartiles"] == 3
    assert Decimal(result["minimum_quartile_lower_mean_net_r"]) == Decimal("-3.5")
    assert Decimal(result["minimum_quartile_upper_mean_net_r"]) == Decimal("-1.5")
    for low, high in (([], []), ([Decimal(0)] * 3, [Decimal(0)] * 3),
                      ([Decimal(0)] * 4, [Decimal(0)] * 5),
                      ([Decimal(1)] * 4, [Decimal(0)] * 4)):
        with pytest.raises(ValueError, match="chronological quartile"):
            _chronological_quartile_net_r_envelope(low, high)


def test_chronological_quartile_envelopes_match_independent_outcome_oracle():
    # 3**5 interval populations, 2**5 endpoint outcome paths per population.
    # A quartile here may contain two paths, so the oracle also checks means.
    from decimal import localcontext
    with localcontext() as ctx:
        ctx.prec = 80
        for intervals in product(((-2, 0), (-1, 1), (0, 2)), repeat=5):
            lower = [Decimal(a) for a, _ in intervals]
            upper = [Decimal(b) for _, b in intervals]
            actual = _chronological_quartile_net_r_envelope(lower, upper)
            possible_worst = []
            positive_counts = []
            for endpoints in product((0, 1), repeat=5):
                realized = [Decimal(intervals[i][endpoint]) for i, endpoint in enumerate(endpoints)]
                means = []
                for q in range(4):
                    start, end = q * 5 // 4, (q + 1) * 5 // 4
                    means.append(sum(realized[start:end], Decimal(0)) / Decimal(end - start))
                possible_worst.append(min(means))
                positive_counts.append(sum(mean > 0 for mean in means))
            assert Decimal(actual["minimum_quartile_lower_mean_net_r"]) == min(possible_worst)
            assert Decimal(actual["minimum_quartile_upper_mean_net_r"]) == max(possible_worst)
            assert actual["guaranteed_positive_quartiles"] == min(positive_counts)
            assert actual["possible_positive_quartiles"] == max(positive_counts)


def test_full_report_chronological_quartiles_cost_monotonic_and_nonexecuting():
    manifest, paths = sample()
    report = run(manifest, paths)
    for label in ("training", "holdout"):
        key = f"{label}_pseudo_settlement_chronological_quartiles"
        previous = None
        for scenario in report["cost_scenarios"]:
            value = scenario[key]
            rows = value["quartiles"]
            assert [row["quartile"] for row in rows] == [1, 2, 3, 4]
            assert sum(row["booked_paths"] for row in rows) == report[
                "admission_counts"][f"{label}_admitted"]
            assert rows[0]["start_booking_event"] == 0
            assert rows[-1]["end_booking_event"] == report[
                "admission_counts"][f"{label}_admitted"]
            if previous is not None:
                assert value["guaranteed_positive_quartiles"] <= previous[
                    "guaranteed_positive_quartiles"]
                assert value["possible_positive_quartiles"] <= previous[
                    "possible_positive_quartiles"]
                for current_row, prior_row in zip(rows, previous["quartiles"]):
                    assert (current_row["start_booking_event"], current_row["end_booking_event"]) == (
                        prior_row["start_booking_event"], prior_row["end_booking_event"])
                    for bound in ("lower_mean_net_r", "upper_mean_net_r"):
                        assert Decimal(current_row[bound]) <= Decimal(prior_row[bound])
            previous = value
    assert report["source_authenticated"] is False
    assert report["untouched_holdout_verified"] is False
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False


def test_worst_single_deletion_mean_is_not_winner_selection():
    lower = [Decimal("-3"), Decimal("1"), Decimal("5")]
    upper = [Decimal("-2"), Decimal("2"), Decimal("6")]
    result = _worst_single_deletion_mean_envelope(lower, upper)
    assert result["booked_paths"] == 3
    assert Decimal(result["minimum_worst_deletion_mean_net_r"]) == Decimal("-1")
    assert Decimal(result["maximum_worst_deletion_mean_net_r"]) == Decimal("0")
    assert result["minimum_worst_deletion_removed_booking_event"] == 3
    assert result["maximum_worst_deletion_removed_booking_event"] == 3
    assert result["guaranteed_strict_positive_after_any_one_deletion"] is False
    assert result["possible_strict_positive_after_any_one_deletion"] is False
    ties = _worst_single_deletion_mean_envelope(
        [Decimal(1)] * 4, [Decimal(2)] * 4)
    assert ties["minimum_worst_deletion_removed_booking_event"] == 1
    assert ties["maximum_worst_deletion_removed_booking_event"] == 1
    assert ties["guaranteed_strict_positive_after_any_one_deletion"] is True
    for low, high in (([], []), ([Decimal(1)], [Decimal(1)]),
                      ([Decimal(0)] * 3, [Decimal(0)] * 2),
                      ([Decimal(1)] * 2, [Decimal(0)] * 2)):
        with pytest.raises(ValueError, match="single-deletion"):
            _worst_single_deletion_mean_envelope(low, high)


def test_worst_single_deletion_bounds_match_independent_endpoint_oracle():
    # 3**5 interval populations * 2**5 endpoint realizations = 7,776.
    # The worst deletion is reselected for EACH realized outcome; the
    # envelope must not assume the same removed booking event every time.
    for intervals in product(((-2, 0), (-1, 1), (0, 2)), repeat=5):
        lower = [Decimal(a) for a, _ in intervals]
        upper = [Decimal(b) for _, b in intervals]
        actual = _worst_single_deletion_mean_envelope(lower, upper)
        outcomes = []
        for endpoint_bits in product((0, 1), repeat=5):
            realized = [
                Decimal(intervals[i][bit]) for i, bit in enumerate(endpoint_bits)]
            outcomes.append(min(
                sum((realized[k] for k in range(5) if k != removed),
                    Decimal(0)) / Decimal(4)
                for removed in range(5)))
        assert Decimal(actual["minimum_worst_deletion_mean_net_r"]) == min(outcomes)
        assert Decimal(actual["maximum_worst_deletion_mean_net_r"]) == max(outcomes)
        assert actual["guaranteed_strict_positive_after_any_one_deletion"] == (
            min(outcomes) > 0)
        assert actual["possible_strict_positive_after_any_one_deletion"] == (
            max(outcomes) > 0)


def test_full_report_worst_single_deletion_is_cost_monotone_and_nonexecuting():
    manifest, paths = sample()
    report = run(manifest, paths)
    for label in ("training", "holdout"):
        key = f"{label}_pseudo_settlement_worst_single_deletion_mean"
        previous = None
        for scenario in report["cost_scenarios"]:
            current = scenario[key]
            assert current["booked_paths"] == report[
                "admission_counts"][f"{label}_admitted"]
            for event_key in ("minimum_worst_deletion_removed_booking_event",
                              "maximum_worst_deletion_removed_booking_event"):
                assert 1 <= current[event_key] <= current["booked_paths"]
            if previous is not None:
                for bound in ("minimum_worst_deletion_mean_net_r",
                              "maximum_worst_deletion_mean_net_r"):
                    assert Decimal(current[bound]) <= Decimal(previous[bound])
                for flag in ("guaranteed_strict_positive_after_any_one_deletion",
                             "possible_strict_positive_after_any_one_deletion"):
                    assert not current[flag] or previous[flag]
            previous = current
    assert report["source_authenticated"] is False
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False
