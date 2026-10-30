"""Synthetic, timestamp-only M15 horizon population regressions."""
import pytest

from app.source_m1_population_audit import audit_source_m1_population

T = 1_790_000_100
assert T % 900 == 0


def audit(source, stored, **kwargs):
    return audit_source_m1_population(
        source, stored, source_id="synthetic:horizon", **kwargs
    )


def minutes(bars):
    return [T + i * 60 for i in range(bars * 15)]


@pytest.mark.parametrize("bars,horizon,expected", [
    (33, 34, 0), (34, 34, 1), (35, 34, 2),
    (40, 34, 7), (40, 1, 40), (40, 40, 1), (40, 41, 0),
])
def test_overlapping_candidate_start_count(bars, horizon, expected):
    m = minutes(bars)
    result = audit(m, m, horizon_bars=horizon)
    assert result["common_clean_m15_horizon_candidate_start_count"] == expected
    assert result["common_clean_m15_horizon_qualifying_run_count"] == int(expected > 0)
    assert result["declared_clean_m15_horizon_bars"] == horizon
    assert result["horizon_candidates_are_structural_only"] is True
    assert result["research_ready"] is False
    assert result["may_execute_order"] is False


def test_horizon_candidate_samples_cover_first_and_last_possible_starts():
    m = minutes(40)
    result = audit(m, m, horizon_bars=34)
    sample = result["common_clean_m15_horizon_candidate_samples"][0]
    from datetime import datetime, timezone
    iso = lambda epoch: datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    assert sample == {
        "first_candidate_start_utc": iso(T),
        "last_candidate_start_utc": iso(T + 6 * 900),
        "candidate_starts": 7,
    }


def test_missing_complete_bucket_splits_horizon_and_never_bridges_gap():
    m = minutes(70)
    # Remove the entire 35th M15 bucket, leaving 34 and 35 clean buckets.
    m = [t for t in m if not (T + 34 * 900 <= t < T + 35 * 900)]
    result = audit(m, m, horizon_bars=34)
    assert result["common_clean_m15_contiguous_run_count"] == 2
    assert result["common_clean_m15_horizon_qualifying_run_count"] == 2
    assert result["common_clean_m15_horizon_candidate_start_count"] == 3


def test_replayed_source_minute_removes_entire_m15_bucket_from_horizons():
    m = minutes(70)
    raw = m + [m[35 * 15 + 7]]
    result = audit(raw, m, horizon_bars=34)
    assert result["stored_complete_m15_buckets_touched_by_repeated_source_minutes"] == 1
    assert result["common_clean_m15_horizon_candidate_start_count"] == 3
    assert result["result"] == "QUARANTINE_REQUIRED"
    assert result["research_ready"] is False


def test_samples_disabled_preserves_counts_and_does_not_mutate_input():
    m = minutes(40)
    before = m[:]
    result = audit(m, m, sample_limit=0)
    assert result["common_clean_m15_horizon_candidate_start_count"] == 7
    assert result["common_clean_m15_horizon_candidate_samples"] == []
    assert m == before
    assert result == audit(m, m, sample_limit=0)


def test_no_clean_buckets_gives_zero_candidates():
    m = minutes(34)
    result = audit(m + m, m)
    assert result["common_clean_m15_horizon_candidate_start_count"] == 0
    assert result["common_clean_m15_horizon_qualifying_run_count"] == 0
    assert result["common_clean_m15_horizon_candidate_samples"] == []


@pytest.mark.parametrize("bad", [True, False, 0, -1, 1001, 34.0, "34", None])
def test_invalid_horizon_fails_closed(bad):
    with pytest.raises(ValueError):
        audit([T], [T], horizon_bars=bad)
