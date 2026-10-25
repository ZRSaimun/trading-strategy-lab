"""Synthetic-only cost capacity regression tests; not historical performance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import (
    audit_frozen_bracket_population, fingerprint_population_manifest,
)
from app.frozen_cost_capacity import (
    audit_frozen_cost_capacity, summarize_frozen_cost_capacity,
)

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
SOURCE = dict(instrument="NSXUSD-CFD", provider="synthetic", venue="synthetic",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def sample(n=36):
    eligible, paths = [], []
    for i in range(n):
        at = int((BASE + timedelta(weeks=i)).timestamp())
        frozen = dict(path_id=f"p{i}", signal_at=at, direction="LONG",
                      entry="100", stop="99", target="102")
        eligible.append(frozen)
        paths.append(dict(**SOURCE, **frozen, entry_at=at + 60,
                          bars=[dict(at=at + 60, open="100", high="101",
                                     low="99.5", close="100.5")]))
    manifest = dict(protocol="m1-bracket-population-v1", source=deepcopy(SOURCE),
                    eligible_signals=eligible, excluded_signals=[])
    return manifest, paths


def run(manifest, paths, digest=None):
    return audit_frozen_cost_capacity(
        manifest, paths,
        digest if digest is not None else fingerprint_population_manifest(manifest),
    )


def test_full_population_cost_capacity_is_descriptive_only():
    manifest, paths = sample()
    result = run(manifest, paths)
    assert result["status"] == "DESCRIPTIVE_COST_CAPACITY_ONLY"
    assert result["eligible_signals"] == 36
    assert result["gross_total_lower_r"] == "18.0"
    assert result["gross_total_upper_r"] == "18.0"
    assert result["additional_notional_cost_r_per_bps"] == "0.36"
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] == "50.000000"
    assert result["zero_mean_upper_bound_cost_bps_floor_6dp"] == "50.000000"
    assert [x["additional_round_trip_bps"] for x in result["cost_scenarios"]] == [0, 5, 10, 20]
    assert [x["total_lower_net_r"] for x in result["cost_scenarios"]] == [
        "18.0", "16.20", "14.40", "10.80",
    ]
    assert result["largest_tested_bps_with_positive_lower_bound"] == 20
    assert result["first_tested_bps_with_nonpositive_upper_bound"] is None
    assert result["verified_profitability"] is False
    assert result["executable_broker_fills"] is False
    assert result["untouched_holdout_verified"] is False


def test_all_losing_population_has_no_positive_cost_budget():
    manifest, paths = sample()
    for path in paths:
        path["bars"][0]["close"] = "99.5"
    result = run(manifest, paths)
    assert result["gross_total_lower_r"] == "-18.0"
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] is None
    assert result["zero_mean_upper_bound_cost_bps_floor_6dp"] is None
    assert result["largest_tested_bps_with_positive_lower_bound"] is None
    assert result["first_tested_bps_with_nonpositive_upper_bound"] == 0
    assert all(x["upper_bound_nonpositive"] for x in result["cost_scenarios"])


def test_intrabar_ambiguity_never_becomes_a_certain_win():
    manifest, paths = sample()
    for path in paths:
        path["bars"][0].update(high="103", low="98", close="100")
    result = run(manifest, paths)
    assert result["gross_total_lower_r"] == "-36"
    assert result["gross_total_upper_r"] == "72"
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] is None
    assert result["zero_mean_upper_bound_cost_bps_floor_6dp"] == "200.000000"
    assert all(x["zero_within_bounds"] for x in result["cost_scenarios"])


def test_mixed_intrabar_bounds_have_separate_cost_thresholds():
    manifest, paths = sample()
    paths[0]["bars"][0].update(high="103", low="98", close="100")
    result = run(manifest, paths)
    assert result["gross_total_lower_r"] == "16.5"
    assert result["gross_total_upper_r"] == "19.5"
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] == "45.833333"
    assert result["zero_mean_upper_bound_cost_bps_floor_6dp"] == "54.166666"


def test_zero_gross_return_is_not_called_positive():
    manifest, paths = sample()
    for path in paths:
        path["bars"][0]["close"] = "100"
    result = run(manifest, paths)
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] is None
    assert result["first_tested_bps_with_nonpositive_upper_bound"] == 0


def test_small_positive_cost_threshold_is_floored_not_rounded_up():
    manifest, paths = sample()
    for path in paths:
        path["bars"][0]["close"] = "100.000000001"
    result = run(manifest, paths)
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] == "0.000000"


def test_short_direction_uses_same_absolute_notional_sensitivity():
    manifest, paths = sample()
    for frozen, path in zip(manifest["eligible_signals"], paths):
        frozen.update(direction="SHORT", stop="101", target="98")
        path.update(direction="SHORT", stop="101", target="98")
        path["bars"][0].update(close="99.5", high="100.5", low="99")
    result = run(manifest, paths)
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] == "50.000000"


def test_negative_historical_price_uses_absolute_notional():
    manifest, paths = sample()
    for frozen, path in zip(manifest["eligible_signals"], paths):
        frozen.update(entry="-35", stop="-37", target="-31")
        path.update(entry="-35", stop="-37", target="-31")
        path["bars"][0].update(open="-35", high="-33", low="-36", close="-34")
    result = run(manifest, paths)
    assert result["gross_total_lower_r"] == "18.0"
    assert result["additional_notional_cost_r_per_bps"] == "0.0630"
    assert result["zero_mean_lower_bound_cost_bps_floor_6dp"] == "285.714285"


def test_input_order_is_canonical():
    manifest, paths = sample()
    original = run(manifest, paths)
    manifest["eligible_signals"].reverse()
    paths.reverse()
    assert run(manifest, paths) == original


def test_missing_outcome_rejected_not_survivor_filtered():
    manifest, paths = sample()
    with pytest.raises(ValueError, match="Incomplete"):
        run(manifest, paths[:-1])


def test_censored_outcome_withholds_all_cost_capacity():
    manifest, paths = sample()
    paths[0]["bars"] = []
    result = run(manifest, paths)
    assert result["status"] == "WITHHELD_INCOMPLETE_OR_INSUFFICIENT"
    assert result["cost_scenarios"] == []


def test_pre_signal_exclusion_withholds_cost_capacity():
    manifest, paths = sample()
    manifest["excluded_signals"].append(dict(
        path_id="excluded", signal_at=int((BASE + timedelta(weeks=40)).timestamp()),
        reason="PRE_SIGNAL_DATA_GAP",
    ))
    assert run(manifest, paths)["cost_scenarios"] == []


def test_insufficient_sample_withholds():
    manifest, paths = sample(29)
    assert run(manifest, paths)["cost_scenarios"] == []


def test_insufficient_week_dispersion_withholds():
    manifest, paths = sample()
    for i in range(36):
        at = int((BASE + timedelta(weeks=i // 3, minutes=i % 3)).timestamp())
        manifest["eligible_signals"][i]["signal_at"] = at
        paths[i]["signal_at"] = at
        paths[i]["entry_at"] = at + 60
        paths[i]["bars"][0]["at"] = at + 60
    assert run(manifest, paths)["cost_scenarios"] == []


def test_external_frozen_digest_change_rejected():
    manifest, paths = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(manifest, paths, "f" * 64)


def test_changed_frozen_source_rejected():
    manifest, paths = sample()
    paths[0]["venue"] = "changed"
    with pytest.raises(ValueError, match="source"):
        run(manifest, paths)


def test_duplicate_path_rejected():
    manifest, paths = sample()
    paths[1]["path_id"] = paths[0]["path_id"]
    with pytest.raises(ValueError, match="Duplicate"):
        run(manifest, paths)


def test_tampered_upstream_costs_rejected():
    manifest, paths = sample()
    audit = audit_frozen_bracket_population(
        manifest, paths, fingerprint_population_manifest(manifest))
    audit["outcome_audit"]["paths"][0]["cost_scenarios"][0]["lower_net_r"] = "999"
    with pytest.raises(ValueError, match="linear cost"):
        summarize_frozen_cost_capacity(audit, manifest)


def test_tampered_upstream_cost_identity_rejected():
    manifest, paths = sample()
    audit = audit_frozen_bracket_population(
        manifest, paths, fingerprint_population_manifest(manifest))
    audit["outcome_audit"]["cost_scenarios"][1]["additional_round_trip_bps"] = 7
    with pytest.raises(ValueError, match="upstream cost identity"):
        summarize_frozen_cost_capacity(audit, manifest)


def test_future_entry_or_invalid_prices_are_not_silently_accepted():
    manifest, paths = sample()
    paths[0]["entry_at"] += 60
    with pytest.raises(ValueError, match="next-minute"):
        run(manifest, paths)
    manifest, paths = sample()
    paths[0]["bars"][0]["close"] = "NaN"
    with pytest.raises(ValueError, match="decimal"):
        run(manifest, paths)
