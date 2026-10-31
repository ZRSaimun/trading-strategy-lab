"""Synthetic cost frontier regression tests; no real market data or orders."""
from decimal import Decimal

import pytest

from app.offline_m1_cost_frontier import _group_frontier, audit_m1_cost_frontier
from test_offline_m1_multi_archive_census import receipt, rehash


def sample():
    return [receipt("a", "c", count=2, mean=1),
            receipt("b", "d", count=8, mean=3)]


def test_weighted_fixed_and_mirrored_break_even_cost():
    g = audit_m1_cost_frontier(sample())["groups"][0]
    assert g["evaluated_outcome_count"] == 10
    b = g["break_even_roundtrip_cost_intervals_bps"]
    assert b["fixed_direction"] == {"lower_bps": "2.5999995", "upper_bps": "2.6000005"}
    assert b["mirrored_direction"] == {"lower_bps": "-2.6000005", "upper_bps": "-2.5999995"}
    assert g["scenarios_by_illustrative_cost_bps"]["5"]["fixed_direction"] == "NONPOSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"
    assert g["scenarios_by_illustrative_cost_bps"]["0"]["fixed_direction"] == "POSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"


def test_oracle_hindsight_is_separate_and_nontrading():
    r = [receipt("a", "c", count=2, mean=6), receipt("b", "d", count=2, mean=-6)]
    x = audit_m1_cost_frontier(r)
    g = x["groups"][0]
    assert g["scenarios_by_illustrative_cost_bps"]["5"]["fixed_direction"] == "NONPOSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"
    assert g["scenarios_by_illustrative_cost_bps"]["5"]["mirrored_direction"] == "NONPOSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"
    assert g["scenarios_by_illustrative_cost_bps"]["5"]["hindsight_per_archive_oracle"] == "POSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"
    assert x["hindsight_oracle_is_tradable"] is False


def test_boundary_is_unknown_not_fabricated_profit():
    g = audit_m1_cost_frontier([receipt("a", "c", mean=5), receipt("b", "d", mean=5)])["groups"][0]
    assert g["scenarios_by_illustrative_cost_bps"]["5"]["fixed_direction"] == "ROUNDING_BOUNDARY_UNKNOWN"


def test_just_above_boundary_is_positive_under_rounding():
    g = audit_m1_cost_frontier([receipt("a", "c", mean=5.000001), receipt("b", "d", mean=5.000001)])["groups"][0]
    assert g["scenarios_by_illustrative_cost_bps"]["5"]["fixed_direction"] == "POSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"


def test_oracle_absolute_value_interval_near_zero():
    g = _group_frontier([("a", 1, Decimal("0.000000")), ("b", 1, Decimal("0.000001"))], (0, 5))
    assert g["break_even_roundtrip_cost_intervals_bps"]["hindsight_per_archive_oracle"] == {
        "lower_bps": "0.0000002", "upper_bps": "0.0000010"}
    assert g["scenarios_by_illustrative_cost_bps"]["0"]["hindsight_per_archive_oracle"] == "POSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"


def test_empty_archive_withholds_every_cost_conclusion():
    r = [receipt("a", "c", count=0), receipt("b", "d", count=2, mean=5)]
    g = audit_m1_cost_frontier(r)["groups"][0]
    assert g["status"] == "INCOMPLETE_ARCHIVE_COVERAGE"
    assert g["break_even_roundtrip_cost_intervals_bps"] is None
    assert all(v is None for v in g["scenarios_by_illustrative_cost_bps"].values())


def test_single_archive_not_claimed_as_replication():
    r = sample()
    r[1]["source"]["instrument"] = "XAUUSD"
    rehash(r[1])
    g = audit_m1_cost_frontier(r)["groups"]
    assert [x["instrument"] for x in g] == ["NSXUSD", "XAUUSD"]
    assert all(x["status"] == "INSUFFICIENT_ARCHIVE_REPLICATION" for x in g)


def test_reorder_determinism_and_bound_hash():
    r = sample()
    x = audit_m1_cost_frontier(r)
    assert x == audit_m1_cost_frontier(list(reversed(r)))
    assert len(x["research_sha256"]) == 64
    assert x["source_robustness_sha256"]


def test_rehashed_seven_decimal_mean_rejected():
    r = sample()
    for part in ("development_exploratory", "later_exploratory_not_holdout", "all_exploratory"):
        r[1][part]["mean_gross_bps"] = 3.0000001
        r[1][part]["mean_net_bps_by_roundtrip_cost"] = {str(c): 3.0000001-c for c in (0,5,10,20)}
    rehash(r[1])
    with pytest.raises(ValueError, match="six decimals"):
        audit_m1_cost_frontier(r)


def test_rehashed_seven_decimal_win_fraction_rejected():
    r = sample()
    r[1]["all_exploratory"]["gross_win_fraction"] = 0.3750001
    rehash(r[1])
    with pytest.raises(ValueError, match="six decimals"):
        audit_m1_cost_frontier(r)


def test_rehashed_seven_decimal_net_scenario_rejected():
    r = sample()
    r[1]["all_exploratory"]["mean_net_bps_by_roundtrip_cost"]["5"] = -1.9999999
    rehash(r[1])
    with pytest.raises(ValueError, match="six decimals"):
        audit_m1_cost_frontier(r)


def test_tamper_and_duplicate_rejected_by_upstream():
    r = sample()
    r[1]["all_exploratory"]["mean_gross_bps"] = 12
    with pytest.raises(ValueError, match="fingerprint"):
        audit_m1_cost_frontier(r)
    r = sample()
    r[1]["source"]["archive_sha256"] = r[0]["source"]["archive_sha256"]
    rehash(r[1])
    with pytest.raises(ValueError, match="Duplicate"):
        audit_m1_cost_frontier(r)


def test_all_safety_flags_false():
    x = audit_m1_cost_frontier(sample())
    assert x["research_only"] is True
    for field in ("trade_authorized", "verified_profitability", "protected_holdout",
                  "source_authenticity_verified", "executable_quotes_verified",
                  "statistical_significance_verified", "hindsight_oracle_is_tradable"):
        assert x[field] is False
