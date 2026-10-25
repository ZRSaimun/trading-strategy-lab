"""Synthetic-only four-week shock tests; never historical performance evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_four_week_shock import audit_frozen_four_week_shock

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
SOURCE = dict(instrument="NSXUSD-CFD", provider="synthetic", venue="synthetic",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def sample(n=36, step_weeks=1):
    eligible, paths = [], []
    for i in range(n):
        at = int((BASE + timedelta(weeks=i * step_weeks)).timestamp())
        frozen = dict(path_id=f"p{i}", signal_at=at, direction="LONG",
                      entry="100", stop="99", target="102")
        eligible.append(frozen)
        paths.append(dict(**SOURCE, **frozen, entry_at=at + 60,
                          bars=[dict(at=at + 60, open="100", high="100.5",
                                     low="99.5", close="99.5")]))
    manifest = dict(protocol="m1-bracket-population-v1", source=deepcopy(SOURCE),
                    eligible_signals=eligible, excluded_signals=[])
    return manifest, paths


def run(manifest, paths):
    return audit_frozen_four_week_shock(
        manifest, paths, fingerprint_population_manifest(manifest))


def test_complete_four_week_stress_and_costs():
    manifest, paths = sample()
    result = run(manifest, paths)
    assert result["status"] == "DESCRIPTIVE_FOUR_WEEK_SHOCK_ONLY"
    assert result["calendar_week_span"] == 36
    assert result["active_utc_weeks"] == 36
    assert result["zero_signal_calendar_weeks"] == 0
    assert result["rolling_window_calendar_weeks"] == 4
    assert result["most_populated_window_start_utc"] == "2026-01-05"
    assert result["most_populated_window_signals"] == 4
    assert [r["additional_round_trip_bps"] for r in result["cost_scenarios"]] == [0, 5, 10, 20]
    zero, five = result["cost_scenarios"][:2]
    assert zero["total_lower_net_r"] == "-18.0"
    assert zero["worst_four_week_lower_net_r"] == "-2.0"
    assert zero["best_four_week_lower_net_r"] == "-2.0"
    assert zero["leave_best_four_week_out_lower_total_r"] == "-16.0"
    assert five["total_lower_net_r"] == "-19.80"
    assert five["worst_four_week_lower_net_r"] == "-2.20"
    assert five["leave_best_four_week_out_lower_total_r"] == "-17.60"
    assert result["verified_profitability"] is False
    assert result["executable_broker_fills"] is False


def test_best_four_week_cluster_exposes_concentration():
    manifest, paths = sample()
    for path in paths[:4]:
        path["bars"][0]["high"] = "101.5"
        path["bars"][0]["close"] = "101.5"
    zero = run(manifest, paths)["cost_scenarios"][0]
    assert zero["total_lower_net_r"] == "-10.0"
    assert zero["best_four_week_lower_net_r"] == "6.0"
    assert zero["worst_four_week_lower_net_r"] == "-2.0"
    assert zero["leave_best_four_week_out_lower_total_r"] == "-16.0"


def test_empty_calendar_week_is_not_removed():
    manifest, paths = sample()
    at = manifest["eligible_signals"][0]["signal_at"] + 86400
    manifest["eligible_signals"][1]["signal_at"] = at
    paths[1]["signal_at"] = at
    paths[1]["entry_at"] = at + 60
    paths[1]["bars"][0]["at"] = at + 60
    result = run(manifest, paths)
    assert result["calendar_week_span"] == 36
    assert result["active_utc_weeks"] == 35
    assert result["zero_signal_calendar_weeks"] == 1
    assert result["most_populated_window_signals"] == 5


def test_intrabar_uncertainty_retained_as_distinct_bounds():
    manifest, paths = sample()
    paths[0]["bars"][0] = dict(at=paths[0]["entry_at"], open="100",
                               high="103", low="98", close="100")
    result = run(manifest, paths)["cost_scenarios"][0]
    assert result["total_lower_net_r"] == "-18.5"
    assert result["total_upper_net_r"] == "-15.5"
    assert result["best_four_week_upper_net_r"] == "1.0"


def test_canonical_order_of_paths_and_manifest():
    manifest, paths = sample()
    expected = run(manifest, paths)
    manifest["eligible_signals"].reverse()
    paths.reverse()
    assert run(manifest, paths) == expected


@pytest.mark.parametrize("n,step", [(29, 1), (36, 0), (36, 20)])
def test_insufficient_or_excessive_time_span_withholds(n, step):
    if step == 0:
        manifest, paths = sample()
        # Collapse into 12 active weeks with three distinct minute clocks each.
        for i in range(36):
            at = int((BASE + timedelta(weeks=i // 3, minutes=i % 3)).timestamp())
            manifest["eligible_signals"][i]["signal_at"] = at
            paths[i]["signal_at"] = at
            paths[i]["entry_at"] = at + 60
            paths[i]["bars"][0]["at"] = at + 60
    else:
        manifest, paths = sample(n, step)
    result = run(manifest, paths)
    assert result["status"] == "WITHHELD_INCOMPLETE_OR_INSUFFICIENT"
    assert result["cost_scenarios"] == []


def test_censored_path_withholds_without_survivor_filter():
    manifest, paths = sample()
    paths[0]["bars"] = []
    assert run(manifest, paths)["cost_scenarios"] == []


def test_declared_exclusion_withholds():
    manifest, paths = sample()
    manifest["excluded_signals"].append(dict(
        path_id="excluded", signal_at=int((BASE + timedelta(weeks=50)).timestamp()),
        reason="PRE_SIGNAL_DATA_GAP"))
    assert run(manifest, paths)["cost_scenarios"] == []


def test_changed_external_manifest_hash_rejected():
    manifest, paths = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        audit_frozen_four_week_shock(manifest, paths, "f" * 64)


def test_duplicate_and_changed_source_rejected():
    manifest, paths = sample()
    paths[1]["path_id"] = paths[0]["path_id"]
    with pytest.raises(ValueError):
        run(manifest, paths)
    manifest, paths = sample()
    paths[1]["venue"] = "changed"
    with pytest.raises(ValueError):
        run(manifest, paths)


def test_no_future_bar_or_shifted_entry_accepted():
    manifest, paths = sample()
    paths[0]["bars"][0]["at"] += 60
    assert run(manifest, paths)["cost_scenarios"] == []
    manifest, paths = sample()
    paths[0]["entry_at"] += 60
    with pytest.raises(ValueError):
        run(manifest, paths)
