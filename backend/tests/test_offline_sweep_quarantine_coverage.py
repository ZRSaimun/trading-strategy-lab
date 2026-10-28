"""Synthetic-only post-outcome window-coverage diagnostics; never trade filters."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from app.offline_sweep_probe import Bar
from app.offline_sweep_duplicate_bucket_sensitivity import (
    _full_horizon_window_coverage, audit_declared_duplicate_minutes,
)

START = datetime(2025, 1, 1)


def candles(n=120):
    return [
        Bar(START + timedelta(minutes=15 * i), Decimal("100"),
            Decimal("101"), Decimal("99"), Decimal("100"), 0)
        for i in range(n)
    ]


def cell(bars, touched=(), cohort="development"):
    return _full_horizon_window_coverage(bars, set(touched))["cohorts"][cohort]


def test_full_horizon_envelope_reconciles_split_embargo_and_end_boundary():
    b = candles()
    dev, later = cell(b), cell(b, cohort="exploratory_later")
    assert dev == {
        "possible_sweep_indices": 51,
        "full_horizon_outside_cohort_or_archive": 16,
        "full_horizon_crosses_source_gap_or_segment": 0,
        "original_contiguous_full_horizon_windows": 35,
        "declared_duplicate_touched_full_horizon_windows": 0,
        "quarantine_clean_full_horizon_windows": 35,
    }
    assert later["possible_sweep_indices"] == 19
    assert later["full_horizon_outside_cohort_or_archive"] == 16
    assert later["original_contiguous_full_horizon_windows"] == 3


def test_one_duplicate_bucket_affects_all_overlapping_windows_not_just_itself():
    b = candles()
    dev = cell(b, [b[20].time])
    assert dev["original_contiguous_full_horizon_windows"] == 35
    assert dev["declared_duplicate_touched_full_horizon_windows"] == 21
    assert dev["quarantine_clean_full_horizon_windows"] == 14
    assert cell(b, [b[20].time], "exploratory_later")[
        "quarantine_clean_full_horizon_windows"] == 3


def test_source_segment_break_and_clock_gap_both_reduce_original_coverage():
    b = candles()
    segmented = [replace(x, segment=1) if i >= 30 else x
                 for i, x in enumerate(b)]
    assert cell(segmented)["full_horizon_crosses_source_gap_or_segment"] == 30
    assert cell(segmented)["original_contiguous_full_horizon_windows"] == 5
    shifted = [replace(x, time=x.time + timedelta(minutes=15)) if i >= 30
               else x for i, x in enumerate(b)]
    assert cell(shifted)["full_horizon_crosses_source_gap_or_segment"] == 30
    assert cell(shifted)["original_contiguous_full_horizon_windows"] == 5


def test_all_complete_buckets_touched_and_no_signal_or_price_selection():
    b = candles()
    all_times = [x.time for x in b]
    assert cell(b, all_times)["quarantine_clean_full_horizon_windows"] == 0
    altered = [replace(x, o=Decimal("100.5"), c=Decimal("100.5"))
               for x in b]
    assert cell(b, [b[20].time]) == cell(altered, [b[20].time])
    report = _full_horizon_window_coverage(b, {b[20].time})
    assert report["does_not_measure_trade_or_signal_count"] is True
    assert report["does_not_prove_executable_or_profitable_outcomes"] is True


def test_integrated_declared_report_exposes_envelope_without_changing_bars():
    b = candles()
    original = list(b)
    result = audit_declared_duplicate_minutes(
        b, ["2025-01-01T05:01:00"],
        dataset_id="a" * 64, archive_sha256="b" * 64,
    )
    assert result["full_horizon_window_coverage"]["cohorts"]["development"][
        "declared_duplicate_touched_full_horizon_windows"] == 21
    assert result["retained_m15_count"] == len(b)
    assert result["matched_trade_population_preserved"] is False
    assert result["verified_profitability"] is False
    assert b == original
