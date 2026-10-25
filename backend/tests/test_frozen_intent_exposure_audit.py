"""Synthetic population tests; no source data, historical returns or execution."""
from copy import deepcopy

import pytest

from app.frozen_next_open_intent import fingerprint_next_open_intents
from app.frozen_intent_exposure_audit import audit_frozen_intent_exposure

SOURCE = dict(instrument="XAUUSD", provider="fixture", venue="fixture",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=3)
T = 1767600000  # Minute-aligned UTC epoch; synthetic.


def manifest(minutes=(0, 1, 3), horizon=3, excluded=False):
    return dict(protocol="frozen-next-open-intent-v1",
                source=dict(SOURCE, horizon_minutes=horizon),
                eligible_intents=[dict(path_id=f"p{i}", signal_at=T + m * 60,
                                       direction="LONG", stop="95", target="105")
                                  for i, m in enumerate(minutes)],
                excluded_signals=([dict(path_id="excluded", signal_at=T - 60,
                                        reason="PRE_SIGNAL_DATA_GAP")] if excluded else []))


def audit(m, **kwargs):
    return audit_frozen_intent_exposure(m, fingerprint_next_open_intents(m), **kwargs)


def test_half_open_adjacent_exposure_not_overlap():
    result = audit(manifest((0, 3, 6)))
    assert result["potential_overlapping_pairs"] == 0
    assert result["maximum_potential_concurrent_intents"] == 1
    assert result["status"] == "NO_FULL_HORIZON_OVERLAP_OBSERVED"
    assert result["verified_profitability"] is False


def test_pair_and_chain_overlap_without_discarding_signals():
    result = audit(manifest((0, 1, 3)))
    assert result["eligible_intents"] == 3
    assert result["potential_overlapping_pairs"] == 2
    assert result["eligible_intents_in_potential_overlaps"] == 3
    assert result["maximum_potential_concurrent_intents"] == 2
    assert result["status"] == "POTENTIAL_EXPOSURE_COLLISIONS"
    assert [x["second_path_id"] for x in result["adjacent_overlap_samples"]] == ["p1", "p2"]


def test_three_simultaneous_potential_positions_count_all_pairs():
    result = audit(manifest((0, 1, 2), horizon=5))
    assert result["potential_overlapping_pairs"] == 3
    assert result["maximum_potential_concurrent_intents"] == 3
    assert result["eligible_intents_in_potential_overlaps"] == 3


def test_one_minute_horizon_never_overlaps_distinct_signal_minutes():
    assert audit(manifest((0, 1, 2), horizon=1))["potential_overlapping_pairs"] == 0


def test_exclusions_are_preserved_not_silently_ignored():
    result = audit(manifest((0, 3), excluded=True))
    assert result["declared_excluded_signals"] == 1
    assert result["status"] == "DECLARED_PRE_SIGNAL_EXCLUSIONS"
    assert result["independent_trade_returns_established"] is False


def test_hash_mismatch_and_invalid_hash_rejected():
    m = manifest()
    with pytest.raises(ValueError, match="mismatch"):
        audit_frozen_intent_exposure(m, "b" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        audit_frozen_intent_exposure(m, "bad")


def test_frozen_population_mutation_rejected():
    m = manifest()
    digest = fingerprint_next_open_intents(m)
    m["eligible_intents"].pop()
    with pytest.raises(ValueError, match="mismatch"):
        audit_frozen_intent_exposure(m, digest)


def test_input_order_independent_and_unchanged():
    m = manifest()
    original = deepcopy(m)
    a = audit(m)
    m["eligible_intents"].reverse()
    b = audit(m)
    assert a == b
    assert original["eligible_intents"] == list(reversed(m["eligible_intents"]))


@pytest.mark.parametrize("limit", [-1, 51, True, 1.0])
def test_invalid_sample_limit_rejected(limit):
    with pytest.raises(ValueError, match="sample limit"):
        audit(manifest(), sample_limit=limit)


def test_zero_samples_still_counts_all_overlaps():
    r = audit(manifest(), sample_limit=0)
    assert r["adjacent_overlap_samples"] == []
    assert r["potential_overlapping_pairs"] == 2


def test_clock_overflow_rejected_before_reporting():
    m = manifest((0,), horizon=1440)
    m["eligible_intents"][0]["signal_at"] = 8640000000 - 60
    with pytest.raises(ValueError, match="horizon"):
        audit(m)


def test_duplicate_signal_clocks_rejected_by_existing_manifest_gate():
    m = manifest((0, 0))
    with pytest.raises(ValueError, match="Duplicate"):
        fingerprint_next_open_intents(m)
