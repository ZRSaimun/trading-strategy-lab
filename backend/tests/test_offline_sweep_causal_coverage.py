"""Synthetic-only causal confirmation denominator; never signal or trade admission."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from app.offline_sweep_probe import Bar
from app.offline_sweep_duplicate_bucket_sensitivity import (
    _causal_confirmation_window_coverage, _full_horizon_window_coverage,
    audit_declared_duplicate_minutes,
)

START = datetime(2025, 1, 1)


def bars(n=120):
    return [
        Bar(START + timedelta(minutes=15 * i), Decimal("100"),
            Decimal("101"), Decimal("99"), Decimal("100"), 0)
        for i in range(n)
    ]


def cell(data, touched=(), cohort="development"):
    return _causal_confirmation_window_coverage(
        data, set(touched))["cohorts"][cohort]


def test_causal_denominator_matches_frozen_sweep_index_split_and_embargo():
    b = bars()
    assert cell(b) == {
        "possible_sweep_indices": 51,
        "confirmation_crosses_source_gap_or_segment": 0,
        "original_contiguous_confirmation_windows": 51,
        "declared_duplicate_touched_confirmation_windows": 0,
        "quarantine_clean_confirmation_windows": 51,
    }
    assert cell(b, cohort="exploratory_later")[
        "possible_sweep_indices"] == 19


def test_duplicate_affects_only_causal_18_bar_windows_not_future_outcomes():
    b = bars()
    assert cell(b, [b[20].time])[
        "declared_duplicate_touched_confirmation_windows"] == 18
    assert cell(b, [b[20].time])[
        "quarantine_clean_confirmation_windows"] == 33
    assert _full_horizon_window_coverage(b, {b[20].time})[
        "cohorts"]["development"][
            "declared_duplicate_touched_full_horizon_windows"] == 21


def test_gap_and_segment_break_reconcile_without_inspecting_future():
    b = bars()
    changed = [replace(x, segment=1) if i >= 30 else x
               for i, x in enumerate(b)]
    assert cell(changed)["confirmation_crosses_source_gap_or_segment"] == 17
    assert cell(changed)["original_contiguous_confirmation_windows"] == 34
    shifted = [replace(x, time=x.time + timedelta(minutes=15))
               if i >= 30 else x for i, x in enumerate(b)]
    assert cell(shifted) == cell(changed)


def test_future_prices_do_not_affect_causal_denominator():
    b = bars()
    touched = {b[20].time}
    original = _causal_confirmation_window_coverage(b, touched)
    altered = [replace(x, o=Decimal("100.5"), c=Decimal("100.5"))
               for x in b]
    assert _causal_confirmation_window_coverage(altered, touched) == original
    assert original["future_entry_or_exit_bars_inspected"] is False
    assert original["does_not_measure_trade_or_signal_count"] is True


def test_no_candidate_windows_in_short_archive_and_no_mutation():
    b = bars(18)
    before = list(b)
    report = _causal_confirmation_window_coverage(b, set())
    assert all(v["possible_sweep_indices"] == 0
               for v in report["cohorts"].values())
    assert b == before


def test_integrated_report_has_both_distinct_denominators():
    b = bars()
    result = audit_declared_duplicate_minutes(
        b, ["2025-01-01T05:01:00"],
        dataset_id="a" * 64, archive_sha256="b" * 64,
    )
    assert result["causal_confirmation_window_coverage"][
        "cohorts"]["development"][
            "declared_duplicate_touched_confirmation_windows"] == 18
    assert result["full_horizon_window_coverage"][
        "cohorts"]["development"][
            "declared_duplicate_touched_full_horizon_windows"] == 21
    assert result["verified_profitability"] is False
    assert result["may_execute_order"] is False
