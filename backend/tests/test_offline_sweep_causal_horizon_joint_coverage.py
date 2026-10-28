"""Synthetic-only regression tests for causal/full-horizon structural joint census."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.offline_sweep_probe import Bar
from app.offline_sweep_causal_horizon_joint_coverage import (
    audit_causal_horizon_joint_coverage,
)

DATASET = "a" * 64
ARCHIVE = "b" * 64
START = datetime(2025, 1, 1)
CAUSAL = ("gap_or_segment", "declared_duplicate_touched", "quarantine_clean")
HORIZON = ("outside_cohort_or_archive", "gap_or_segment",
           "declared_duplicate_touched", "quarantine_clean")


def bars(n=120):
    return [
        Bar(START + timedelta(minutes=15 * i), Decimal("100.1"),
            Decimal("101"), Decimal("99"), Decimal("100.2"), 0)
        for i in range(n)
    ]


def minute(i, offset=1):
    return (START + timedelta(minutes=15 * i + offset)).isoformat(
        timespec="seconds")


def audit(candles=None, duplicates=()):
    return audit_causal_horizon_joint_coverage(
        bars() if candles is None else candles, list(duplicates),
        dataset_id=DATASET, archive_sha256=ARCHIVE)


def matrix(report, cohort="development"):
    return report["cohorts"][cohort]["causal_by_retrospective_horizon"]


def test_no_duplicates_reconciles_both_cohorts_and_boundaries():
    report = audit()
    for cohort in ("development", "exploratory_later"):
        cell = report["cohorts"][cohort]
        rows = matrix(report, cohort)
        assert sum(sum(row.values()) for row in rows.values()) == cell[
            "possible_sweep_indices"]
        assert all(rows[c]["quarantine_clean"] == 0 for c in CAUSAL[:2])
        assert all(rows["declared_duplicate_touched"][h] == 0 for h in HORIZON)
        assert rows["quarantine_clean"]["outside_cohort_or_archive"] > 0
        assert rows["quarantine_clean"]["quarantine_clean"] > 0
        assert cell["causal_clean_without_full_clean_horizon"] > 0
    assert report["may_use_horizon_to_select_signals"] is False
    assert report["horizon_classification_is_post_outcome_only"] is True
    assert report["verified_profitability"] is False


def test_single_duplicate_has_three_extra_retrospective_touched_windows():
    rows = matrix(audit(duplicates=[minute(20)]))
    assert sum(rows["declared_duplicate_touched"].values()) == 18
    assert sum(rows[c]["declared_duplicate_touched"] for c in CAUSAL) == 21
    assert rows["quarantine_clean"]["declared_duplicate_touched"] == 3
    assert rows["declared_duplicate_touched"]["quarantine_clean"] == 0


def test_adjacent_duplicate_buckets_count_unique_windows_not_twice():
    rows = matrix(audit(duplicates=[minute(20), minute(21)]))
    assert sum(rows["declared_duplicate_touched"].values()) == 19
    assert sum(rows[c]["declared_duplicate_touched"] for c in CAUSAL) == 22


def test_duplicate_in_future_horizon_never_retroactively_taints_causal():
    rows = matrix(audit(duplicates=[minute(55)]))
    assert rows["quarantine_clean"]["declared_duplicate_touched"] > 0
    assert rows["declared_duplicate_touched"]["quarantine_clean"] == 0


def test_segment_boundary_changes_structural_matrix_without_price_signal():
    candles = bars()
    candles = [
        replace(bar, segment=1) if i >= 30 else bar
        for i, bar in enumerate(candles)
    ]
    rows = matrix(audit(candles))
    assert sum(rows["gap_or_segment"].values()) == 17
    assert rows["gap_or_segment"]["quarantine_clean"] == 0
    assert rows["quarantine_clean"]["gap_or_segment"] > 0


def test_price_only_mutation_does_not_change_joint_structural_report():
    candles = bars()
    changed = list(candles)
    changed[20] = replace(changed[20], c=Decimal("100.3"))
    assert audit(candles, [minute(20)]) == audit(changed, [minute(20)])


@pytest.mark.parametrize("bad", [
    [minute(20), minute(20)],
    [minute(21), minute(20)],
    ["2025-01-01T00:00:00Z"],
])
def test_invalid_duplicate_declarations_fail_closed(bad):
    with pytest.raises(ValueError):
        audit(duplicates=bad)


def test_small_input_has_zero_candidates_and_no_future_reads():
    result = audit(bars(18))
    for cohort in ("development", "exploratory_later"):
        assert result["cohorts"][cohort]["possible_sweep_indices"] == 0


def test_report_does_not_expose_private_source_local_timestamps():
    report = audit(duplicates=[minute(20)])
    assert "2025-01-01T" not in str(report)
    assert report["source_clock"] == "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC"
    assert report["original_source_authenticated"] is False
    assert report["may_execute_order"] is False
