"""Synthetic tests for paired source-local causal quarantine classifications."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.offline_sweep_probe import Bar
from app.offline_sweep_quarantine_transition import audit_quarantine_transition

START = datetime(2025, 1, 1)
DATASET = "a" * 64
ARCHIVE = "b" * 64


def bars(n=120):
    return [Bar(START + timedelta(minutes=15 * i), Decimal("100.1"),
                Decimal("101"), Decimal("99"), Decimal("100.2"), 0)
            for i in range(n)]


def minute(i, offset=1):
    return (START + timedelta(minutes=15 * i + offset)).isoformat(
        timespec="seconds")


def run(baseline=(), revised=(), candles=None):
    return audit_quarantine_transition(
        bars() if candles is None else candles, list(baseline), list(revised),
        dataset_id=DATASET, archive_sha256=ARCHIVE)


def cell(report, cohort="development"):
    return report["cohorts"][cohort]


def test_identical_declarations_have_no_transition():
    report = run([minute(20)], [minute(20)])
    assert cell(report)["changed_causal_windows"] == 0
    assert cell(report)["baseline_class_fingerprints"] == cell(report)[
        "revised_class_fingerprints"]
    assert report["uses_future_entry_or_exit"] is False
    assert report["may_execute_order"] is False


def test_new_duplicate_contaminates_eighteen_development_windows():
    c = cell(run((), [minute(20)]))
    assert c["lost_clean_causal_windows"] == 18
    assert c["gained_clean_causal_windows"] == 0
    assert c["changed_causal_windows"] == 18
    assert c["baseline_by_revised_causal_class"]["quarantine_clean"][
        "declared_duplicate_touched"] == 18


def test_removed_duplicate_restores_eighteen_windows():
    c = cell(run([minute(20)], ()))
    assert c["gained_clean_causal_windows"] == 18
    assert c["lost_clean_causal_windows"] == 0


def test_overlapping_duplicate_buckets_count_unique_changes():
    c = cell(run([minute(20)], [minute(20), minute(21)]))
    assert c["lost_clean_causal_windows"] == 1
    assert c["changed_causal_windows"] == 1


def test_same_quarter_hour_bucket_yields_same_classes():
    assert cell(run([minute(20, 1)], [minute(20, 9)]))[
        "changed_causal_windows"] == 0


def test_missing_complete_bucket_does_not_change_candidate_windows():
    report = run((), ["2024-12-01T00:01:00"])
    assert sum(c["changed_causal_windows"] for c in report["cohorts"].values()) == 0


def test_existing_segment_break_cannot_transition():
    candles = bars()
    candles = [replace(x, segment=1) if i >= 30 else x
               for i, x in enumerate(candles)]
    matrix = cell(run((), [minute(30)], candles))["baseline_by_revised_causal_class"]
    assert matrix["gap_or_segment"]["gap_or_segment"] == 17
    assert all(matrix["gap_or_segment"][k] == 0 for k in (
        "quarantine_clean", "declared_duplicate_touched"))


def test_price_change_does_not_change_structural_counts():
    candles = bars()
    candles[-1] = replace(candles[-1], c=Decimal("100.3"))
    assert run((), [minute(20)])["cohorts"] == run(
        (), [minute(20)], candles)["cohorts"]


def test_fingerprint_is_deterministic_and_changes_with_transition_identity():
    first = cell(run((), [minute(20)]))["changed_window_identity_sha256"]
    assert first == cell(run((), [minute(20)]))["changed_window_identity_sha256"]
    assert first != cell(run((), [minute(21)]))["changed_window_identity_sha256"]


def test_later_cohort_transitions_do_not_change_development():
    baseline = run()
    revised = run((), [minute(110)])
    assert cell(revised)["changed_causal_windows"] == 0
    assert cell(revised, "exploratory_later")["changed_causal_windows"] > 0
    assert cell(baseline, "exploratory_later")["changed_causal_windows"] == 0


@pytest.mark.parametrize("invalid", [
    [minute(20), minute(20)],
    [minute(21), minute(20)],
    ["2025-01-01T05:01:00Z"],
])
def test_invalid_revised_manifest_rejected(invalid):
    with pytest.raises(ValueError):
        run((), invalid)


def test_rejects_invalid_baseline_and_source_identity():
    with pytest.raises(ValueError):
        run([minute(20), minute(20)], ())
    with pytest.raises(ValueError):
        audit_quarantine_transition(bars(), [], [], dataset_id="bad",
                                    archive_sha256=ARCHIVE)


def test_no_raw_timestamps_in_report():
    report = run((), [minute(20)])
    assert "2025-01-01T" not in str(report)
    assert report["source_authenticated"] is False
    assert report["changed_counts_are_matched_trade_effects"] is False
