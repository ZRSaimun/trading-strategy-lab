"""Synthetic only: no market performance or authentic holdout claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_chronological_holdout import audit_frozen_chronological_holdout

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
CUTOFF = int((BASE + timedelta(weeks=36)).timestamp())
SOURCE = dict(instrument="NSXUSD-CFD", provider="synthetic", venue="synthetic",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def sample(n=72):
    frozen, paths = [], []
    for i in range(n):
        at = int((BASE + timedelta(weeks=i)).timestamp())
        signal = dict(path_id=f"p{i}", signal_at=at, direction="LONG",
                      entry="100", stop="99", target="102")
        frozen.append(signal)
        close = "100.5" if i < 36 else "99.5"
        paths.append(dict(**SOURCE, **signal, entry_at=at + 60,
                          bars=[dict(at=at + 60, open="100", high="100.75",
                                     low="99.25", close=close)]))
    return dict(protocol="m1-bracket-population-v1", source=deepcopy(SOURCE),
                eligible_signals=frozen, excluded_signals=[]), paths


def run(manifest, paths, *, cutoff=CUTOFF, embargo=1440, digest=None):
    return audit_frozen_chronological_holdout(
        manifest, paths,
        digest if digest is not None else fingerprint_population_manifest(manifest),
        cutoff, embargo,
    )


def move(manifest, paths, i, at):
    manifest["eligible_signals"][i]["signal_at"] = at
    paths[i]["signal_at"] = at
    paths[i]["entry_at"] = at + 60
    paths[i]["bars"][0]["at"] = at + 60


def test_complete_chronological_comparison_is_descriptive():
    m, p = sample()
    report = run(m, p)
    assert report["status"] == "DESCRIPTIVE_CHRONOLOGICAL_COMPARISON_ONLY"
    assert report["training_signals"] == report["holdout_signals"] == 36
    assert report["training_active_utc_weeks"] == report["holdout_active_utc_weeks"] == 36
    zero = report["cost_scenarios"][0]
    assert zero["training_mean_lower_net_r"] == "0.5"
    assert zero["holdout_mean_upper_net_r"] == "-0.5"
    assert zero["holdout_minus_training_lower_net_r"] == "-1.0"
    assert zero["holdout_minus_training_upper_net_r"] == "-1.0"
    assert zero["holdout_upper_bound_nonpositive"] is True
    assert report["untouched_holdout_verified"] is False
    assert report["may_execute_order"] is False
    assert report["verified_profitability"] is False


def test_explicit_cost_scenarios_change_both_cohorts():
    m, p = sample()
    report = run(m, p)
    assert [x["additional_round_trip_bps"] for x in report["cost_scenarios"]] == [0, 5, 10, 20]
    five = report["cost_scenarios"][1]
    assert five["training_mean_lower_net_r"] == "0.45"
    assert five["holdout_mean_upper_net_r"] == "-0.55"
    assert five["holdout_minus_training_lower_net_r"] == "-1.00"


def test_ambiguous_holdout_is_not_converted_into_winner():
    m, p = sample()
    p[36]["bars"][0].update(high="103", low="98", close="100")
    report = run(m, p)["cost_scenarios"][0]
    assert report["holdout_mean_lower_net_r"] == str(-18.5 / 36) or (
        float(report["holdout_mean_lower_net_r"]) == pytest.approx(-18.5 / 36))
    assert float(report["holdout_mean_upper_net_r"]) == pytest.approx(-15.5 / 36)
    assert float(report["holdout_minus_training_lower_net_r"]) < -1


def test_input_order_does_not_change_report():
    m, p = sample()
    before = run(m, p)
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == before


def test_missing_frozen_path_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="Incomplete"):
        run(m, p[:-1])


def test_duplicate_path_rejected():
    m, p = sample()
    p[1]["path_id"] = p[0]["path_id"]
    with pytest.raises(ValueError, match="Duplicate"):
        run(m, p)


def test_source_change_rejected():
    m, p = sample()
    p[0]["venue"] = "unregistered"
    with pytest.raises(ValueError, match="source"):
        run(m, p)


def test_digest_change_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


def test_censored_path_withholds_all_cohort_returns():
    m, p = sample()
    p[36]["bars"] = []
    result = run(m, p)
    assert result["status"].startswith("WITHHELD")
    assert "Censored" in result["reason"]
    assert result["cost_scenarios"] == []
    assert result["holdout_signals"] == 36


def test_declared_exclusion_withholds_even_if_not_in_holdout():
    m, p = sample()
    m["excluded_signals"].append(dict(
        path_id="excluded", signal_at=int((BASE - timedelta(weeks=1)).timestamp()),
        reason="PRE_SIGNAL_DATA_GAP"))
    result = run(m, p)
    assert result["cost_scenarios"] == []
    assert result["declared_excluded_signals"] == 1


def test_too_few_holdout_signals_withholds():
    m, p = sample(50)
    assert run(m, p)["cost_scenarios"] == []


def test_zero_holdout_signals_withholds():
    m, p = sample(36)
    assert run(m, p)["cost_scenarios"] == []


def test_zero_training_signals_withholds():
    m, p = sample()
    earlier = int((BASE - timedelta(weeks=1)).timestamp())
    assert run(m, p, cutoff=earlier)["cost_scenarios"] == []


def test_insufficient_week_dispersion_withholds():
    m, p = sample()
    for i in range(72):
        week = (i % 36) // 4
        minute = i % 4
        at = int((BASE + timedelta(weeks=week + (36 if i >= 36 else 0),
                                    minutes=minute)).timestamp())
        move(m, p, i, at)
    result = run(m, p)
    assert result["cost_scenarios"] == []
    assert result["training_active_utc_weeks"] == 9
    assert result["holdout_active_utc_weeks"] == 9


def test_training_label_window_near_cutoff_is_not_survivor_filtered():
    m, p = sample()
    at = CUTOFF - 60 * 60
    move(m, p, 35, at)
    result = run(m, p)
    assert result["cost_scenarios"] == []
    assert "label window" in result["reason"]
    assert result["training_signals"] == 36


def test_full_week_embargo_withholds_boundary_training_signal():
    m, p = sample()
    result = run(m, p, embargo=10080)
    assert result["cost_scenarios"] == []
    assert "label window" in result["reason"]


@pytest.mark.parametrize("bad", [False, "2026-09-14", -60, 8640000060, CUTOFF + 60])
def test_invalid_cutoff_rejected(bad):
    m, p = sample()
    with pytest.raises(ValueError, match="Cutoff"):
        run(m, p, cutoff=bad)


@pytest.mark.parametrize("bad", [0, True, -1, 10081, 1.0])
def test_invalid_embargo_rejected(bad):
    m, p = sample()
    with pytest.raises(ValueError, match="embargo"):
        run(m, p, embargo=bad)


def test_holdout_boundary_belongs_only_to_holdout():
    m, p = sample()
    assert p[36]["signal_at"] == CUTOFF
    result = run(m, p)
    assert result["holdout_signals"] == 36


def test_short_direction_is_supported_without_optimistic_sign():
    m, p = sample()
    for signal, path in zip(m["eligible_signals"], p):
        signal.update(direction="SHORT", stop="101", target="98")
        path.update(direction="SHORT", stop="101", target="98")
        path["bars"][0].update(high="100.75", low="99.25",
                               close="99.5" if path["signal_at"] < CUTOFF else "100.5")
    report = run(m, p)["cost_scenarios"][0]
    assert report["training_mean_lower_net_r"] == "0.5"
    assert report["holdout_mean_upper_net_r"] == "-0.5"


def test_malformed_outcome_prices_fail_closed():
    m, p = sample()
    p[36]["bars"][0]["close"] = "NaN"
    with pytest.raises(ValueError, match="decimal"):
        run(m, p)
