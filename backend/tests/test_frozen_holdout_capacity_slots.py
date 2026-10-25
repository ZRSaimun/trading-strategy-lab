"""Synthetic-only fixed-slot admission regressions; no market/profitability claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_holdout_capacity_slots import audit_frozen_holdout_capacity_slots

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
    return audit_frozen_holdout_capacity_slots(
        m, p, kwargs.pop("digest", fingerprint_population_manifest(m)),
        kwargs.pop("cutoff", CUTOFF), kwargs.pop("embargo", 1440), **kwargs)


def test_weekly_separated_all_admitted_with_fixed_equity_bounds():
    m, p = sample()
    r = run(m, p)
    assert r["status"] == "DESCRIPTIVE_FIXED_SLOT_SCENARIOS_ONLY"
    assert r["admission_counts"]["training_admitted"] == 36
    assert r["admission_counts"]["holdout_admitted"] == 36
    assert r["admission_counts"]["holdout_unadmitted"] == 0
    assert r["admission_counts"]["maximum_reserved_full_horizon_slots"] == 1
    assert r["cost_scenarios"][0]["training_fixed_initial_equity_lower_pct"] == "18.0"
    assert r["cost_scenarios"][0]["holdout_fixed_initial_equity_lower_pct"] == "-18.0"
    assert r["may_execute_order"] is False
    assert r["capital_feasible_returns_verified"] is False


def test_one_slot_skips_second_collision_without_selecting_by_outcome():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, max_positions=1)
    assert r["admission_counts"]["holdout_admitted"] == 35
    assert r["admission_counts"]["holdout_unadmitted"] == 1
    assert r["admission_counts"]["unadmitted_by_reason"] == {"SLOT_LIMIT": 1, "RISK_BUDGET": 0}
    assert r["unadmitted_samples"][0]["path_id"] == "p37"
    assert r["cost_scenarios"][0]["holdout_fixed_initial_equity_lower_pct"] == "-17.5"
    assert r["full_population_opportunity_cost_scenarios"][0]["holdout_mean_lower_net_r"] == "-0.5"


def test_two_slots_accept_collision_when_risk_budget_allows():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, max_positions=2, total_risk_budget_bps=200)
    assert r["admission_counts"]["holdout_admitted"] == 36
    assert r["admission_counts"]["maximum_reserved_full_horizon_slots"] == 2


def test_risk_budget_binds_even_when_slots_free():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, max_positions=3, per_position_risk_bps=100, total_risk_budget_bps=100)
    assert r["policy"]["effective_full_horizon_slots"] == 1
    assert r["admission_counts"]["unadmitted_by_reason"]["RISK_BUDGET"] == 1


def test_future_early_exit_never_releases_slot_for_admission():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    # First trade touches target on first bar; no hindsight early release.
    p[36]["bars"][0].update(high="103", low="99.25", close="100")
    r = run(m, p)
    assert r["admission_counts"]["holdout_unadmitted"] == 1
    assert r["unadmitted_samples"][0]["path_id"] == "p37"


def test_half_open_full_horizon_boundary_admits_next():
    m, p = sample()
    move(m, p, 37, CUTOFF + 180)
    r = run(m, p)
    assert r["admission_counts"]["holdout_unadmitted"] == 0


def test_three_way_chain_one_slot_two_rejections():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    move(m, p, 38, CUTOFF + 120)
    r = run(m, p)
    assert r["admission_counts"]["holdout_unadmitted"] == 2
    assert [x["path_id"] for x in r["unadmitted_samples"]] == ["p37", "p38"]


def test_order_invariance_and_no_mutation():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    before = deepcopy((m, p))
    a = run(m, p)
    assert (m, p) == before
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == a


def test_cost_scenarios_reduce_net_return_bounds():
    m, p = sample()
    r = run(m, p)
    assert [x["additional_round_trip_bps"] for x in r["cost_scenarios"]] == [0, 5, 10, 20]
    values = [float(x["holdout_fixed_initial_equity_lower_pct"]) for x in r["cost_scenarios"]]
    assert values == sorted(values, reverse=True)


def test_ambiguous_outcomes_preserve_lower_upper_bounds():
    m, p = sample()
    p[40]["bars"][0].update(high="103", low="98", close="100")
    r = run(m, p)
    s = r["cost_scenarios"][0]
    assert float(s["holdout_fixed_initial_equity_lower_pct"]) < float(s["holdout_fixed_initial_equity_upper_pct"])


def test_censored_path_withholds_all_capacity_return_stats():
    m, p = sample()
    p[40]["bars"] = []
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []
    assert r["admission_counts"] is None


def test_declared_exclusions_withhold():
    m, p = sample()
    m["excluded_signals"].append(dict(path_id="ex", signal_at=int((BASE - timedelta(weeks=1)).timestamp()),
                                      reason="PRE_SIGNAL_DATA_GAP"))
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["declared_excluded_signals"] == 1


def test_small_admitted_holdout_withholds_subgroup_statistics_not_census():
    m, p = sample()
    for i in range(37, 54):
        move(m, p, i, CUTOFF + (i - 36) * 60)
    r = run(m, p)
    assert r["status"] == "INSUFFICIENT_ADMITTED_COHORT_FOR_RETURN_STATISTICS"
    assert r["cost_scenarios"] == []
    assert r["admission_counts"]["holdout_unadmitted"] > 6
    assert r["eligible_signals"] == 72


def test_bad_cutoff_embargo_or_digest_fails_closed():
    m, p = sample()
    with pytest.raises(ValueError):
        run(m, p, cutoff=CUTOFF + 60)
    with pytest.raises(ValueError):
        run(m, p, embargo=0)
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


@pytest.mark.parametrize("kwargs", [
    {"max_positions": 0}, {"max_positions": True}, {"max_positions": 101},
    {"per_position_risk_bps": 0}, {"per_position_risk_bps": 1001},
    {"total_risk_budget_bps": 0}, {"total_risk_budget_bps": 10001},
    {"sample_limit": -1}, {"sample_limit": 51}, {"sample_limit": 1.2},
    {"per_position_risk_bps": 201, "total_risk_budget_bps": 200},
])
def test_invalid_policy_rejected(kwargs):
    m, p = sample()
    with pytest.raises(ValueError):
        run(m, p, **kwargs)


def test_no_sample_output_keeps_all_rejection_counts():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, sample_limit=0)
    assert r["unadmitted_samples"] == []
    assert r["admission_counts"]["holdout_unadmitted"] == 1
