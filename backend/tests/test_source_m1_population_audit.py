"""Synthetic timestamp-only M1 population audits; no files, DB, network or prices."""
import pytest

from app.source_m1_population_audit import audit_source_m1_population

T = 1_790_000_100  # UTC quarter-hour aligned
assert T % 900 == 0


def audit(source, stored, **kwargs):
    return audit_source_m1_population(source, stored, source_id=kwargs.pop("source_id", "synthetic:v1"), **kwargs)


def test_clean_population_is_not_certified_as_market_data():
    minutes = [T + 60 * i for i in range(30)]
    result = audit(minutes, minutes)
    assert result["result"] == "STRUCTURAL_PARITY_ONLY_UNVERIFIED"
    assert result["source_order_complete_m15_windows"] == 2
    assert result["stored_complete_m15_windows"] == 2
    assert result["source_repeated_rows"] == 0
    assert result["price_tuple_parity_verified"] is False
    assert result["research_ready"] is False
    assert result["may_execute_order"] is False


def test_nonadjacent_60_minute_replay_exposes_four_extra_m15_windows():
    original = [T + 60 * i for i in range(120)]
    raw = original[:90] + original[15:75] + original[90:]
    result = audit(raw, original, sample_limit=2)
    assert result["source_rows"] == 180
    assert result["source_distinct_minutes"] == 120
    assert result["source_repeated_rows"] == 60
    assert result["source_backward_timestamp_jumps"] == 1
    assert result["source_unique_missing_from_store"] == 0
    assert result["stored_minutes_absent_from_source"] == 0
    assert result["source_order_complete_m15_windows"] == 12
    assert result["stored_complete_m15_windows"] == 8
    assert result["source_minus_stored_complete_m15_windows"] == 4
    assert result["source_order_repeated_complete_m15_windows"] == 4
    assert len(result["source_order_repeated_m15_bucket_samples_utc"]) == 2
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_adjacent_duplicate_without_m15_delta_is_still_quarantined():
    minutes = [T + 60 * i for i in range(15)]
    result = audit(minutes[:4] + [minutes[3]] + minutes[4:], minutes)
    assert result["source_adjacent_equal_timestamps"] == 1
    assert result["source_repeated_rows"] == 1
    assert result["source_minus_stored_complete_m15_windows"] == -1
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_missing_and_extra_stored_minutes_are_both_reported():
    source = [T, T + 60, T + 120]
    stored = [T, T + 60, T + 180]
    result = audit(source, stored)
    assert result["source_unique_missing_from_store"] == 1
    assert result["stored_minutes_absent_from_source"] == 1
    assert result["result"] == "QUARANTINE_REQUIRED"
    assert len(result["source_missing_from_store_samples_utc"]) == 1
    assert len(result["stored_absent_from_source_samples_utc"]) == 1


def test_samples_zero_still_counts_all_and_does_not_mutate_inputs():
    original = [T + 60 * i for i in range(15)]
    raw = original + original
    snapshot = raw[:]
    result = audit(raw, original, sample_limit=0)
    assert result["source_repeated_rows"] == 15
    assert result["source_order_repeated_complete_m15_windows"] == 1
    assert result["source_repeated_row_samples"] == []
    assert result["source_order_repeated_m15_bucket_samples_utc"] == []
    assert raw == snapshot
    assert result == audit(raw, original, sample_limit=0)


def test_gap_does_not_form_a_complete_m15_window():
    minutes = [T + 60 * i for i in range(15) if i != 7]
    result = audit(minutes, minutes)
    assert result["source_order_complete_m15_windows"] == 0
    assert result["stored_complete_m15_windows"] == 0


@pytest.mark.parametrize("source,stored", [
    ([], [T]), ([T], []),
    ([True], [T]), ([T + 1], [T]),
    ([T], [T, T]), ([T], [T + 60, T]),
    ([T], [253402300800]), ([T], "not-a-list"),
    ((T,), [T]),
])
def test_invalid_inventories_fail_closed(source, stored):
    with pytest.raises(ValueError):
        audit(source, stored)


@pytest.mark.parametrize("source_id", ["", "a b", "../bad", "x" * 129, None, True])
def test_source_id_is_bounded(source_id):
    with pytest.raises(ValueError):
        audit([T], [T], source_id=source_id)


@pytest.mark.parametrize("sample_limit", [-1, 21, True, 1.2, "5"])
def test_sample_limit_is_bounded(sample_limit):
    with pytest.raises(ValueError):
        audit([T], [T], sample_limit=sample_limit)


def test_over_budget_fails_before_population_analysis():
    with pytest.raises(ValueError):
        audit([T] * 1_000_001, [T])


def test_contiguous_replayed_block_has_one_60_row_run():
    original = [T + 60 * i for i in range(120)]
    raw = original[:90] + original[15:75] + original[90:]
    result = audit(raw, original, sample_limit=1)
    assert result["source_repeated_row_run_count"] == 1
    assert result["source_longest_repeated_row_run"] == 60
    assert result["source_repeated_row_run_samples"][0]["first_row_ordinal"] == 91
    assert result["source_repeated_row_run_samples"][0]["last_row_ordinal"] == 150
    assert result["source_repeated_row_run_samples"][0]["repeated_rows"] == 60


def test_separated_repeated_runs_are_counted_without_time_continuity_assumptions():
    original = [T + 60 * i for i in range(15)]
    raw = original[:10] + original[2:4] + original[10:] + [original[4]]
    result = audit(raw, original, sample_limit=2)
    assert result["source_repeated_rows"] == 3
    assert result["source_repeated_row_run_count"] == 2
    assert result["source_longest_repeated_row_run"] == 2
    assert [s["repeated_rows"] for s in result["source_repeated_row_run_samples"]] == [2, 1]
    assert [(s["first_row_ordinal"], s["last_row_ordinal"]) for s in result["source_repeated_row_run_samples"]] == [(11, 12), (18, 18)]
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_run_census_kept_when_samples_disabled():
    original = [T + 60 * i for i in range(15)]
    result = audit(original + original, original, sample_limit=0)
    assert result["source_repeated_row_run_count"] == 1
    assert result["source_longest_repeated_row_run"] == 15
    assert result["source_repeated_row_run_samples"] == []


def test_clean_population_has_no_repeated_runs():
    original = [T + 60 * i for i in range(15)]
    result = audit(original, original)
    assert result["source_repeated_row_run_count"] == 0
    assert result["source_longest_repeated_row_run"] == 0
    assert result["source_repeated_row_run_samples"] == []
