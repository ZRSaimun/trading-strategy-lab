"""Synthetic-only pseudo-settlement drawdown regression tests."""
from copy import deepcopy
from decimal import Decimal
from itertools import product

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_capacity_drawdown import (_maximum_drawdown,
                                          _maximum_drawdown_with_window,
                                          _terminal_drawdown,
                                          _first_pseudo_recovery_event,
                                          _first_pseudo_loss_barrier_event,
                                          _longest_strict_negative_streak,
                                          _strict_sign_count_envelope,
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



def test_terminal_underwater_differs_from_historical_maximum_drawdown():
    seq = [Decimal("2"), Decimal("-3"), Decimal("3"), Decimal("-1")]
    assert _maximum_drawdown(seq) == 3
    assert _terminal_drawdown(seq) == 1
    assert _terminal_drawdown([Decimal("1"), Decimal("2")]) == 0
    assert _terminal_drawdown([Decimal("-1"), Decimal("-2")]) == 3


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
