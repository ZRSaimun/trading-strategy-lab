"""Synthetic-only exposure/holdout integration tests; no authentic market data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_holdout_exposure import audit_frozen_holdout_exposure

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
CUTOFF = int((BASE + timedelta(weeks=36)).timestamp())
SOURCE = dict(instrument="NSXUSD-CFD", provider="synthetic", venue="synthetic",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=2)


def sample(horizon=2, n=72):
    source = dict(SOURCE, horizon_minutes=horizon)
    eligible, paths = [], []
    for i in range(n):
        at = int((BASE + timedelta(weeks=i)).timestamp())
        signal = dict(path_id=f"p{i}", signal_at=at, direction="LONG",
                      entry="100", stop="99", target="102")
        bars = [dict(at=at + 60 * (j + 1), open="100", high="100.75",
                     low="99.25", close="99.5" if i >= 36 else "100.5")
                for j in range(horizon)]
        eligible.append(signal)
        paths.append(dict(**source, **signal, entry_at=at + 60, bars=bars))
    return dict(protocol="m1-bracket-population-v1", source=deepcopy(source),
                eligible_signals=eligible, excluded_signals=[]), paths


def move(m, p, index, new_signal_at):
    m["eligible_signals"][index]["signal_at"] = new_signal_at
    p[index]["signal_at"] = new_signal_at
    p[index]["entry_at"] = new_signal_at + 60
    for j, bar in enumerate(p[index]["bars"]):
        bar["at"] = new_signal_at + 60 * (j + 1)


def run(m, p, *, cutoff=CUTOFF, embargo=1440, digest=None, sample_limit=20):
    return audit_frozen_holdout_exposure(
        m, p, fingerprint_population_manifest(m) if digest is None else digest,
        cutoff, embargo, sample_limit=sample_limit,
    )


def test_weekly_separated_complete_population_has_no_full_horizon_overlap():
    m, p = sample()
    r = run(m, p)
    assert r["status"] == "DESCRIPTIVE_POTENTIAL_EXPOSURE_ONLY"
    assert r["eligible_signals"] == 72
    assert r["training_signals"] == r["holdout_signals"] == 36
    assert r["potential_overlap_pairs"] == 0
    assert r["maximum_potential_concurrent_signals"] == 1
    assert r["overlap_free_under_full_horizon"] is True
    assert r["holdout_signals_affected_by_potential_overlap"] == 0
    assert r["may_execute_order"] is False


def test_holdout_overlap_preserves_all_losing_signals_and_cost_bounds():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p)
    assert r["holdout_signals"] == 36
    assert r["potential_overlap_pairs"] == r["holdout_potential_overlap_pairs"] == 1
    assert r["training_potential_overlap_pairs"] == 0
    assert r["holdout_signals_affected_by_potential_overlap"] == 2
    assert r["holdout_active_utc_weeks_with_potential_overlap"] == 1
    assert r["maximum_potential_concurrent_signals"] == 2
    assert r["cost_scenarios"][0]["holdout_mean_lower_net_r"] == "-0.5"
    assert r["capital_feasible_returns_verified"] is False
    assert r["verified_profitability"] is False


def test_chain_counts_pairs_not_only_adjacent_pairs():
    m, p = sample(horizon=3)
    move(m, p, 37, CUTOFF + 60)
    move(m, p, 38, CUTOFF + 120)
    r = run(m, p)
    assert r["potential_overlap_pairs"] == 3
    assert r["holdout_signals_affected_by_potential_overlap"] == 3
    assert r["maximum_potential_concurrent_signals"] == 3
    assert len(r["adjacent_overlap_samples"]) == 2


def test_half_open_endpoints_are_not_overlap():
    m, p = sample(horizon=2)
    move(m, p, 37, CUTOFF + 120)
    r = run(m, p)
    assert r["potential_overlap_pairs"] == 0


def test_training_only_overlap_is_counted_separately():
    m, p = sample()
    move(m, p, 1, int(BASE.timestamp()) + 60)
    r = run(m, p)
    assert r["training_potential_overlap_pairs"] == 1
    assert r["holdout_potential_overlap_pairs"] == 0
    assert r["training_signals_affected_by_potential_overlap"] == 2
    assert r["training_active_utc_weeks_with_potential_overlap"] == 1


def test_cohort_embargo_prevents_cross_boundary_false_claims():
    m, p = sample()
    move(m, p, 35, CUTOFF - 3600)
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []
    assert r["potential_overlap_pairs"] is None


def test_censored_holdout_withholds_exposure_adjusted_research_report():
    m, p = sample()
    p[40]["bars"] = []
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []


def test_censored_training_also_withholds():
    m, p = sample()
    p[0]["bars"] = []
    assert run(m, p)["cost_scenarios"] == []


def test_declared_exclusions_not_silently_discarded():
    m, p = sample()
    m["excluded_signals"].append(dict(path_id="excluded", signal_at=int((BASE - timedelta(weeks=1)).timestamp()),
                                      reason="PRE_SIGNAL_DATA_GAP"))
    r = run(m, p)
    assert r["declared_excluded_signals"] == 1
    assert r["cost_scenarios"] == []


def test_input_order_independent_and_does_not_mutate_population():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    baseline = run(m, p)
    before = deepcopy((m, p))
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == baseline
    assert before[0]["eligible_signals"] == list(reversed(m["eligible_signals"]))


def test_no_samples_still_reports_full_overlap_population():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p, sample_limit=0)
    assert r["potential_overlap_pairs"] == 1
    assert r["adjacent_overlap_samples"] == []


@pytest.mark.parametrize("limit", [-1, 51, True, 1.0])
def test_invalid_sample_limit_rejected(limit):
    m, p = sample()
    with pytest.raises(ValueError, match="sample limit"):
        run(m, p, sample_limit=limit)


def test_digest_mismatch_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


def test_changed_source_identity_rejected():
    m, p = sample()
    p[40]["provider"] = "other"
    with pytest.raises(ValueError, match="source"):
        run(m, p)


def test_missing_frozen_path_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="Incomplete"):
        run(m, p[:-1])


def test_bad_cutoff_and_embargo_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="Cutoff"):
        run(m, p, cutoff=CUTOFF + 60)
    with pytest.raises(ValueError, match="embargo"):
        run(m, p, embargo=0)


def test_ambiguous_intrabar_path_does_not_disappear():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    p[37]["bars"][0].update(high="103", low="98", close="100")
    r = run(m, p)
    assert r["holdout_signals"] == 36
    assert r["holdout_potential_overlap_pairs"] == 1
    assert float(r["cost_scenarios"][0]["holdout_mean_lower_net_r"]) < -0.5
    assert float(r["cost_scenarios"][0]["holdout_mean_upper_net_r"]) > -0.5
