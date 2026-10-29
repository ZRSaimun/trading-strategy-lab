"""Synthetic-only tests of matched-window direction and hindsight costs."""
import copy

import pytest

from app.offline_m1_paired_direction_cost_falsification import (
    audit_m1_paired_direction_cost_falsification as audit,
)
from test_offline_m1_multi_archive_census import receipt, rehash


def sample():
    return [
        receipt("a", "c", count=2, mean=0),
        receipt("b", "d", count=8, mean=10),
        receipt("e", "f", count=10, mean=-2),
        receipt("1", "2", count=4, mean=4),
    ]


def test_weighted_mirror_and_impossible_hindsight_upper_bound():
    g = audit(sample())["groups"][0]
    assert g["evaluated_outcome_count"] == 24
    assert g["status"] == "DESCRIPTIVE_HINDSIGHT_FALSIFICATION_ONLY"
    s = g["scenarios_by_illustrative_cost_bps"]["5"]
    assert s["fixed_direction_net_bps"] == pytest.approx(76 / 24 - 5, abs=1e-6)
    assert s["mirrored_direction_net_bps"] == pytest.approx(-76 / 24 - 5, abs=1e-6)
    assert s["hindsight_per_archive_oracle_net_bps"] == pytest.approx(116 / 24 - 5, abs=1e-6)
    assert s["fixed_positive_archive_count"] == 1
    assert s["mirrored_positive_archive_count"] == 0
    assert s["hindsight_positive_archive_count"] == 1
    assert s["neither_direction_positive_for_any_archive_mean"] is False


def test_hindsight_oracle_can_look_positive_when_both_fixed_directions_fail():
    r = [receipt("a", "c", count=2, mean=6),
         receipt("b", "d", count=2, mean=-6)]
    s = audit(r)["groups"][0]["scenarios_by_illustrative_cost_bps"]["5"]
    assert s["fixed_direction_net_bps"] == -5
    assert s["mirrored_direction_net_bps"] == -5
    assert s["hindsight_per_archive_oracle_net_bps"] == 1
    assert s["hindsight_positive_archive_count"] == 2


def test_zero_is_not_profitable_and_cost_boundary_is_strict():
    r = [receipt("a", "c", count=2, mean=5),
         receipt("b", "d", count=2, mean=-5)]
    s = audit(r)["groups"][0]["scenarios_by_illustrative_cost_bps"]["5"]
    assert s["hindsight_per_archive_oracle_net_bps"] == 0
    assert s["hindsight_positive_archive_count"] == 0
    assert s["neither_direction_positive_for_any_archive_mean"] is True


def test_large_cost_cannot_be_rescued_by_archive_mean_direction_flip():
    s = audit(sample())["groups"][0]["scenarios_by_illustrative_cost_bps"]["20"]
    assert s["neither_direction_positive_for_any_archive_mean"] is True
    assert s["hindsight_per_archive_oracle_net_bps"] < 0


def test_empty_archive_withholds_all_directional_results():
    r = sample()
    r[0] = receipt("a", "c", count=0)
    g = audit(r)["groups"][0]
    assert g["status"] == "INCOMPLETE_ARCHIVE_COVERAGE"
    for scenario in g["scenarios_by_illustrative_cost_bps"].values():
        assert all(value is None for value in scenario.values())


def test_source_isolation_and_single_archive_is_not_replication():
    r = sample()
    r[0]["source"]["instrument"] = "XAUUSD"
    rehash(r[0])
    x = audit(r)
    assert [g["instrument"] for g in x["groups"]] == ["NSXUSD", "XAUUSD"]
    assert x["groups"][1]["status"] == "INSUFFICIENT_ARCHIVE_REPLICATION"


def test_reorder_determinism_and_hash_binding():
    r = sample()
    a = audit(r)
    assert a == audit(list(reversed(r)))
    changed = copy.deepcopy(r)
    changed[0]["all_exploratory"]["mean_gross_bps"] = 9
    with pytest.raises(ValueError, match="fingerprint"):
        audit(changed)


def test_duplicate_archive_rejected_by_prior_census():
    r = sample()
    r[1]["source"]["archive_sha256"] = r[0]["source"]["archive_sha256"]
    rehash(r[1])
    with pytest.raises(ValueError, match="Duplicate"):
        audit(r)


def test_hindsight_and_trading_flags_always_false():
    x = audit(sample())
    assert x["cost_grid_bps"] == [0, 5, 10, 20]
    assert x["research_only"] is True
    for key in (
        "trade_authorized", "verified_profitability", "protected_holdout",
        "source_authenticity_verified", "executable_quotes_verified",
        "statistical_significance_verified", "hindsight_oracle_is_tradable",
    ):
        assert x[key] is False
