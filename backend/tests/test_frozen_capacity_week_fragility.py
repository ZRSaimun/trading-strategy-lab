"""Synthetic-only regression tests: no market data, broker fills or edge claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_capacity_week_fragility import audit_frozen_capacity_week_fragility

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
CUTOFF = int((BASE + timedelta(weeks=36)).timestamp())
SOURCE = dict(instrument="NSXUSD-CFD", provider="synthetic", venue="synthetic",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=3)


def sample(n=72):
    eligible, paths = [], []
    for i in range(n):
        at = int((BASE + timedelta(weeks=i)).timestamp())
        signal = dict(path_id=f"p{i}", signal_at=at, direction="LONG",
                      entry="100", stop="99", target="102")
        bars = [dict(at=at + 60 * (j + 1), open="100", high="100.75",
                     low="99.25", close="99.5" if i >= 36 else "100.5")
                for j in range(3)]
        eligible.append(signal)
        paths.append(dict(**SOURCE, **signal, entry_at=at + 60, bars=bars))
    return dict(protocol="m1-bracket-population-v1", source=deepcopy(SOURCE),
                eligible_signals=eligible, excluded_signals=[]), paths


def move(m, p, index, new_at):
    m["eligible_signals"][index]["signal_at"] = new_at
    p[index]["signal_at"] = new_at
    p[index]["entry_at"] = new_at + 60
    for j, bar in enumerate(p[index]["bars"]):
        bar["at"] = new_at + 60 * (j + 1)


def run(m, p, **kwargs):
    return audit_frozen_capacity_week_fragility(
        m, p, kwargs.pop("digest", fingerprint_population_manifest(m)),
        kwargs.pop("cutoff", CUTOFF), kwargs.pop("embargo", 1440), **kwargs
    )


def test_all_admitted_negative_holdout_and_complete_counts():
    m, p = sample()
    r = run(m, p)
    assert r["status"] == "DESCRIPTIVE_CAPACITY_ADMITTED_WEEK_FRAGILITY_ONLY"
    assert r["eligible_signals"] == 72
    assert r["admission_counts"]["training_admitted"] == 36
    assert r["admission_counts"]["holdout_admitted"] == 36
    assert r["admitted_holdout_active_utc_weeks"] == 36
    assert r["minimum_remaining_admitted_holdout_signals"] == 35
    assert r["cost_scenarios"][0]["original_admitted_holdout_mean_lower_net_r"] == "-0.5"
    assert r["cost_scenarios"][0]["minimum_leave_one_week_out_mean_lower_net_r"] == "-0.5"
    assert r["cost_scenarios"][0]["deletions_with_nonpositive_upper_bound"] == 36
    assert r["verified_profitability"] is False
    assert r["may_execute_order"] is False


def test_every_cost_scenario_and_nonincreasing_net_returns():
    m, p = sample()
    r = run(m, p)
    assert [x["additional_round_trip_bps"] for x in r["cost_scenarios"]] == [0, 5, 10, 20]
    lo = [float(x["original_admitted_holdout_mean_lower_net_r"]) for x in r["cost_scenarios"]]
    assert lo == sorted(lo, reverse=True)


def test_capacity_skips_overlap_and_reports_rejected_population():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p)
    assert r["admission_counts"]["holdout_unadmitted"] == 1
    assert r["admission_counts"]["holdout_admitted"] == 35
    assert r["maximum_week_admitted_signal_count"] == 1


def test_risk_budget_only_allows_one_slot():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, max_positions=3, per_position_risk_bps=100,
            total_risk_budget_bps=100)
    assert r["policy"]["effective_full_horizon_slots"] == 1
    assert r["admission_counts"]["unadmitted_by_reason"]["RISK_BUDGET"] == 1


def test_two_slots_allow_overlap_without_hindsight():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, max_positions=2, total_risk_budget_bps=200)
    assert r["admission_counts"]["holdout_unadmitted"] == 0
    assert r["maximum_week_admitted_signal_count"] == 2


def test_early_target_touch_does_not_free_capacity_slot():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    p[36]["bars"][0].update(high="103", close="100")
    r = run(m, p)
    assert r["admission_counts"]["holdout_unadmitted"] == 1


def test_positive_one_week_does_not_justify_omitting_it():
    m, p = sample()
    # One profitable holdout week amid 35 losing weeks.
    for bar in p[40]["bars"]:
        bar["close"] = "100.5"
    r = run(m, p)
    s = r["cost_scenarios"][0]
    assert float(s["minimum_leave_one_week_out_mean_lower_net_r"]) < float(s["original_admitted_holdout_mean_lower_net_r"])
    assert s["every_week_deletion_lower_bound_positive"] is False
    assert r["admission_counts"]["holdout_admitted"] == 36


def test_ambiguous_path_keeps_both_return_bounds():
    m, p = sample()
    p[40]["bars"][0].update(high="103", low="98", close="100")
    r = run(m, p)
    s = r["cost_scenarios"][0]
    assert float(s["original_admitted_holdout_mean_lower_net_r"]) < float(s["original_admitted_holdout_mean_upper_net_r"])


def test_invariant_to_manifest_and_path_input_order_and_no_mutation():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    original = deepcopy((m, p))
    a = run(m, p)
    assert (m, p) == original
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == a


def test_censored_path_withholds_all_statistics():
    m, p = sample()
    p[40]["bars"] = []
    r = run(m, p)
    assert r["status"] == "WITHHELD_INCOMPLETE_OR_INSUFFICIENT"
    assert r["cost_scenarios"] == []
    assert r["admission_counts"] is None


def test_declared_exclusion_withholds_statistics():
    m, p = sample()
    m["excluded_signals"].append(dict(path_id="excluded", signal_at=int((BASE - timedelta(weeks=1)).timestamp()),
                                      reason="PRE_SIGNAL_DATA_GAP"))
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["declared_excluded_signals"] == 1


def test_insufficient_after_single_week_removal_withholds():
    m, p = sample()
    # 8 same-week holdout signals are within 3m of each other: one admitted.
    for i in range(37, 45):
        move(m, p, i, CUTOFF + (i - 36) * 60)
    r = run(m, p)
    assert r["status"] == "WITHHELD_INCOMPLETE_OR_INSUFFICIENT"
    assert r["cost_scenarios"] == []
    assert r["admission_counts"]["holdout_unadmitted"] > 0


def test_bad_digest_fails_closed():
    m, p = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


def test_invalid_capacity_policy_fails_closed():
    m, p = sample()
    with pytest.raises(ValueError, match="max_positions"):
        run(m, p, max_positions=0)


def test_cutoff_or_embargo_leakage_fails_closed():
    m, p = sample()
    with pytest.raises(ValueError):
        run(m, p, cutoff=CUTOFF + 60)
    with pytest.raises(ValueError):
        run(m, p, embargo=0)


def test_duplicate_frozen_signal_fails_closed():
    m, p = sample()
    move(m, p, 37, CUTOFF)
    with pytest.raises(ValueError, match="Duplicate or colliding"):
        run(m, p)
