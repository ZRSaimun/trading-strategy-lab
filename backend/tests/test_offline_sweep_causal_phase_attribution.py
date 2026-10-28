"""Synthetic causal-phase attribution of duplicate-touched confirmation windows.

Never use structural counts for signal selection, broker execution, or returns.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from app.offline_sweep_probe import Bar
from app.offline_sweep_duplicate_bucket_sensitivity import (
    _causal_confirmation_window_coverage, audit_declared_duplicate_minutes,
)


START = datetime(2025, 1, 1)


def candles(n=120):
    return [
        Bar(START + timedelta(minutes=15 * i), Decimal("100"),
            Decimal("101"), Decimal("99"), Decimal("100"), 0)
        for i in range(n)
    ]


def phase_report(bars, touched_indices):
    touched = {bars[i].time for i in touched_indices}
    return _causal_confirmation_window_coverage(bars, touched)


def phases(bars, touched_indices, cohort="development"):
    return phase_report(bars, touched_indices)[
        "contamination_phase_attribution"]["cohorts"][cohort]


def test_single_touched_bucket_separates_prior_sweep_and_confirmation():
    b = candles()
    p = phases(b, [20])
    assert p["PRIOR_ONLY"] == 16
    assert p["SWEEP_ONLY"] == 1
    assert p["CONFIRMATION_ONLY"] == 1
    assert sum(p.values()) == 18
    assert all(v == 0 for k, v in p.items()
               if k not in ("PRIOR_ONLY", "SWEEP_ONLY", "CONFIRMATION_ONLY"))


def test_adjacent_touched_buckets_do_not_double_count_overlapping_phases():
    b = candles()
    p = phases(b, [20, 21])
    assert p["PRIOR_ONLY"] == 16
    assert p["CONFIRMATION_ONLY"] == 1
    assert p["SWEEP_AND_CONFIRMATION"] == 1
    assert p["PRIOR_AND_SWEEP"] == 1
    assert sum(p.values()) == 19
    assert sum(p.values()) == phase_report(b, [20, 21])[
        "cohorts"]["development"][
            "declared_duplicate_touched_confirmation_windows"]


def test_all_three_phases_and_nonadjacent_prior_confirmation():
    b = candles()
    assert phases(b, [18, 19, 20])["PRIOR_SWEEP_AND_CONFIRMATION"] == 1
    assert phases(b, [18, 20])["PRIOR_AND_CONFIRMATION"] == 1


def test_existing_segment_break_excludes_noncontiguous_phase_windows():
    b = candles()
    segmented = [replace(x, segment=1) if i >= 30 else x
                 for i, x in enumerate(b)]
    p = phases(segmented, [20])
    assert p["PRIOR_ONLY"] == 8
    assert p["SWEEP_ONLY"] == 1
    assert p["CONFIRMATION_ONLY"] == 1
    assert sum(p.values()) == 10
    assert sum(p.values()) == phase_report(segmented, [20])[
        "cohorts"]["development"][
            "declared_duplicate_touched_confirmation_windows"]


def test_phase_counts_ignore_prices_and_future_entry_exit_data():
    b = candles()
    baseline = phase_report(b, [20, 21])
    altered = [replace(x, o=Decimal("100.5"), c=Decimal("100.5"))
               for x in b]
    assert phase_report(altered, [20, 21]) == baseline
    phase = baseline["contamination_phase_attribution"]
    assert phase["mutually_exclusive"] is True
    assert phase["future_entry_or_exit_bars_inspected"] is False


def test_empty_or_short_cohort_has_all_zero_phase_masks():
    b = candles(18)
    before = list(b)
    report = phase_report(b, [0])
    for counts in report["contamination_phase_attribution"]["cohorts"].values():
        assert len(counts) == 7
        assert sum(counts.values()) == 0
    assert b == before


def test_integrated_declared_report_exposes_causal_phase_census():
    b = candles()
    result = audit_declared_duplicate_minutes(
        b, ["2025-01-01T05:01:00"],
        dataset_id="a" * 64, archive_sha256="b" * 64)
    causal = result["causal_confirmation_window_coverage"]
    assert causal["contamination_phase_attribution"][
        "cohorts"]["development"]["PRIOR_ONLY"] == 16
    assert causal["cohorts"]["development"][
        "declared_duplicate_touched_confirmation_windows"] == 18
    assert result["retained_m15_count"] == 120
    assert result["verified_profitability"] is False
    assert result["may_execute_order"] is False
