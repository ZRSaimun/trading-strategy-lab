"""Synthetic regression tests for source-local causal window identity hashes."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.offline_sweep_probe import Bar
from app.offline_sweep_causal_cohort_identity import audit_causal_cohort_identity

DATASET = "a" * 64
ARCHIVE = "b" * 64
START = datetime(2025, 1, 1)


def bars(n=120, *, start=START):
    return [Bar(start + timedelta(minutes=15 * i), Decimal("100.1"),
                Decimal("101"), Decimal("99"), Decimal("100.2"), 0)
            for i in range(n)]


def audit(candles, duplicates=()):
    return audit_causal_cohort_identity(
        candles, list(duplicates), dataset_id=DATASET, archive_sha256=ARCHIVE)


def minute(index, offset=0):
    return (START + timedelta(minutes=15 * index + offset)).isoformat(
        timespec="seconds")


def count(result, cohort, phase):
    return result["cohorts"][cohort]["classes"][phase]["count"]


def digest(result, cohort, phase):
    return result["cohorts"][cohort]["classes"][phase][
        "source_local_window_identity_sha256"]


def test_no_duplicates_reconciles_all_candidate_windows():
    result = audit(bars())
    for cohort in ("development", "exploratory_later"):
        cell = result["cohorts"][cohort]
        assert sum(x["count"] for x in cell["classes"].values()) == cell[
            "possible_sweep_indices"]
        assert count(result, cohort, "declared_duplicate_touched") == 0
        assert count(result, cohort, "gap_or_segment") == 0
        assert len(digest(result, cohort, "quarantine_clean")) == 64
    assert result["may_execute_order"] is False
    assert result["verified_profitability"] is False


def test_one_touched_bucket_affects_eighteen_causal_windows():
    original = audit(bars())
    touched = audit(bars(), [minute(20, 1)])
    assert count(touched, "development", "declared_duplicate_touched") == 18
    assert count(touched, "development", "quarantine_clean") == (
        count(original, "development", "quarantine_clean") - 18)
    assert digest(touched, "development", "quarantine_clean") != digest(
        original, "development", "quarantine_clean")


def test_same_bucket_different_declared_minutes_have_same_window_identity():
    first = audit(bars(), [minute(20, 1)])
    second = audit(bars(), [minute(20, 9)])
    assert first == second


def test_source_local_time_shift_changes_digest_but_not_population():
    first = audit(bars())
    shifted = audit(bars(start=START + timedelta(minutes=15)))
    assert first["cohorts"]["development"]["possible_sweep_indices"] == (
        shifted["cohorts"]["development"]["possible_sweep_indices"])
    assert digest(first, "development", "quarantine_clean") != digest(
        shifted, "development", "quarantine_clean")


def test_price_changes_do_not_affect_structural_fingerprints():
    original = bars()
    changed = list(original)
    changed[-1] = replace(changed[-1], c=Decimal("100.3"))
    assert audit(original) == audit(changed)


def test_existing_segment_break_is_classified_as_gap():
    candles = bars()
    candles[30] = replace(candles[30], segment=1)
    result = audit(candles)
    assert count(result, "development", "gap_or_segment") == 17
    assert count(result, "development", "declared_duplicate_touched") == 0


def test_overlapping_duplicate_buckets_count_once_per_candidate():
    result = audit(bars(), [minute(20, 1), minute(21, 1)])
    assert count(result, "development", "declared_duplicate_touched") == 19


@pytest.mark.parametrize("bad", [
    [minute(20, 1), minute(20, 1)],
    [minute(21, 1), minute(20, 1)],
    ["2025-01-01T00:00:00Z"],
])
def test_invalid_declarations_fail_closed(bad):
    with pytest.raises(ValueError):
        audit(bars(), bad)


def test_no_source_local_timestamps_leak_into_digest_report():
    result = audit(bars(), [minute(20, 1)])
    assert "2025-01-01T" not in str(result)
    assert result["source_clock"] == "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC"
    assert result["fingerprints_authenticate_source"] is False
    assert result["fingerprints_are_secrecy_protection"] is False
