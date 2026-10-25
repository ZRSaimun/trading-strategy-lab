"""Synthetic-only regression tests; no market returns or authentic holdout."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_holdout_week_stability import audit_frozen_holdout_week_stability

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
CUTOFF = int((BASE + timedelta(weeks=36)).timestamp())
SOURCE = dict(instrument="NSXUSD-CFD", provider="synthetic", venue="synthetic",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def sample(n=72):
    eligible, paths = [], []
    for i in range(n):
        at = int((BASE + timedelta(weeks=i)).timestamp())
        signal = dict(path_id=f"p{i}", signal_at=at, direction="LONG",
                      entry="100", stop="99", target="102")
        eligible.append(signal)
        paths.append(dict(**SOURCE, **signal, entry_at=at + 60,
                          bars=[dict(at=at + 60, open="100", high="100.75",
                                     low="99.25", close="100.5" if i < 36 else "99.5")]))
    manifest = dict(protocol="m1-bracket-population-v1", source=deepcopy(SOURCE),
                    eligible_signals=eligible, excluded_signals=[])
    return manifest, paths


def run(manifest, paths, *, cutoff=CUTOFF, embargo=1440, digest=None):
    return audit_frozen_holdout_week_stability(
        manifest, paths,
        fingerprint_population_manifest(manifest) if digest is None else digest,
        cutoff, embargo,
    )


def move(manifest, paths, i, at):
    manifest["eligible_signals"][i]["signal_at"] = at
    paths[i]["signal_at"] = at
    paths[i]["entry_at"] = at + 60
    paths[i]["bars"][0]["at"] = at + 60


def test_complete_week_deletion_preserves_losing_holdout():
    m, p = sample()
    r = run(m, p)
    assert r["status"] == "DESCRIPTIVE_HOLDOUT_WEEK_STABILITY_ONLY"
    assert r["holdout_signals"] == r["holdout_active_utc_weeks"] == 36
    assert r["minimum_remaining_holdout_signals"] == 35
    zero = r["cost_scenarios"][0]
    assert zero["original_holdout_mean_lower_net_r"] == "-0.5"
    assert zero["minimum_leave_one_week_out_mean_lower_net_r"] == "-0.5"
    assert zero["minimum_leave_one_week_out_mean_upper_net_r"] == "-0.5"
    assert zero["maximum_leave_one_week_out_mean_lower_net_r"] == "-0.5"
    assert zero["deletions_with_nonpositive_upper_bound"] == 36
    assert zero["deletions_with_positive_lower_bound"] == 0
    assert zero["every_week_deletion_lower_bound_positive"] is False
    assert r["untouched_holdout_verified"] is False
    assert r["verified_profitability"] is False
    assert r["may_execute_order"] is False


def test_four_fixed_cost_scenarios_are_not_executable_quotes():
    m, p = sample()
    r = run(m, p)
    assert [x["additional_round_trip_bps"] for x in r["cost_scenarios"]] == [0, 5, 10, 20]
    assert [x["minimum_leave_one_week_out_mean_lower_net_r"] for x in r["cost_scenarios"]] == [
        "-0.5", "-0.55", "-0.6", "-0.7"
    ]


def test_one_favorable_week_is_not_allowed_to_hide_other_losses():
    m, p = sample()
    p[36]["bars"][0].update(high="102.5", close="101")
    r = run(m, p)["cost_scenarios"][0]
    assert r["original_holdout_mean_lower_net_r"] == str((-0.5 * 35 + 2) / 36) or (
        float(r["original_holdout_mean_lower_net_r"]) == pytest.approx((-0.5 * 35 + 2) / 36))
    assert r["minimum_leave_one_week_out_mean_lower_net_r"] == "-0.5"
    assert r["maximum_leave_one_week_out_mean_lower_net_r"] == str((-0.5 * 34 + 2) / 35) or (
        float(r["maximum_leave_one_week_out_mean_lower_net_r"]) == pytest.approx((-0.5 * 34 + 2) / 35))
    assert r["deletions_with_nonpositive_upper_bound"] == 36


def test_ambiguous_intrabar_week_keeps_both_outcome_bounds():
    m, p = sample()
    p[36]["bars"][0].update(high="103", low="98", close="100")
    r = run(m, p)["cost_scenarios"][0]
    assert float(r["original_holdout_mean_lower_net_r"]) < -0.5
    assert float(r["original_holdout_mean_upper_net_r"]) > -0.5
    assert float(r["minimum_leave_one_week_out_mean_lower_net_r"]) <= -0.5
    assert r["deletions_with_nonpositive_upper_bound"] == 36


def test_input_order_independent():
    m, p = sample()
    original = run(m, p)
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == original


def test_holdout_boundary_belongs_to_holdout():
    m, p = sample()
    assert p[36]["signal_at"] == CUTOFF
    assert run(m, p)["holdout_signals"] == 36


def test_training_outcomes_do_not_change_holdout_week_returns():
    m, p = sample()
    baseline = run(m, p)["cost_scenarios"]
    p[0]["bars"][0].update(high="102.5", close="101")
    assert run(m, p)["cost_scenarios"] == baseline


def test_censored_holdout_withholds_all_week_returns():
    m, p = sample()
    p[40]["bars"] = []
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []
    assert r["holdout_signals"] == 36


def test_censored_training_withholds_holdout_week_returns():
    m, p = sample()
    p[0]["bars"] = []
    assert run(m, p)["cost_scenarios"] == []


def test_declared_exclusion_withholds_all_returns():
    m, p = sample()
    m["excluded_signals"].append(dict(path_id="excluded",
                                       signal_at=int((BASE - timedelta(weeks=1)).timestamp()),
                                       reason="PRE_SIGNAL_DATA_GAP"))
    r = run(m, p)
    assert r["cost_scenarios"] == []
    assert r["declared_excluded_signals"] == 1


def test_oversized_holdout_week_deletion_withholds_entire_report():
    m, p = sample()
    for i in range(36, 44):
        move(m, p, i, CUTOFF + (i - 36) * 60)
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []
    assert r["holdout_signals"] == 36


def test_too_few_holdout_weeks_withholds():
    m, p = sample(48)
    assert run(m, p)["cost_scenarios"] == []


def test_training_embargo_leakage_withholds():
    m, p = sample()
    move(m, p, 35, CUTOFF - 3600)
    r = run(m, p)
    assert r["cost_scenarios"] == []
    assert "chronological" in r["reason"]


def test_missing_path_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="Incomplete"):
        run(m, p[:-1])


def test_mutated_source_rejected():
    m, p = sample()
    p[40]["provider"] = "other"
    with pytest.raises(ValueError, match="source"):
        run(m, p)


def test_changed_frozen_manifest_hash_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


def test_invalid_cutoff_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="Cutoff"):
        run(m, p, cutoff=CUTOFF + 60)


def test_invalid_embargo_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="embargo"):
        run(m, p, embargo=0)


def test_short_outcomes_remain_adverse():
    m, p = sample()
    for signal, path in zip(m["eligible_signals"], p):
        signal.update(direction="SHORT", stop="101", target="98")
        path.update(direction="SHORT", stop="101", target="98")
        path["bars"][0].update(high="100.75", low="99.25",
                               close="99.5" if path["signal_at"] < CUTOFF else "100.5")
    r = run(m, p)["cost_scenarios"][0]
    assert r["minimum_leave_one_week_out_mean_upper_net_r"] == "-0.5"


def test_bad_ohlc_rejected():
    m, p = sample()
    p[40]["bars"][0]["close"] = "NaN"
    with pytest.raises(ValueError, match="decimal"):
        run(m, p)
