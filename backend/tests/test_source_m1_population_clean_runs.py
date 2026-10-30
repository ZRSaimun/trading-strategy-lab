"""Synthetic structural M15 clean-run and replay-set audit regressions."""
from app.source_m1_population_audit import audit_source_m1_population

T = 1_790_000_100
assert T % 900 == 0


def check(source, stored, sample_limit=5):
    return audit_source_m1_population(
        source, stored, source_id="synthetic:clean-runs", sample_limit=sample_limit
    )


def test_clean_thirty_minute_population_is_one_two_bucket_run():
    minutes = [T + i * 60 for i in range(30)]
    result = check(minutes, minutes)
    assert result["common_clean_m15_contiguous_run_count"] == 1
    assert result["common_clean_m15_longest_contiguous_run_buckets"] == 2
    assert result["common_clean_m15_contiguous_run_samples"][0]["complete_m15_buckets"] == 2
    assert result["research_ready"] is False


def test_gap_breaks_clean_run_without_inventing_market_closure():
    minutes = [T + i * 60 for i in range(15)] + [
        T + 2700 + i * 60 for i in range(15)
    ]
    result = check(minutes, minutes)
    assert result["common_clean_m15_contiguous_run_count"] == 2
    assert result["common_clean_m15_longest_contiguous_run_buckets"] == 1
    assert [x["complete_m15_buckets"] for x in result["common_clean_m15_contiguous_run_samples"]] == [1, 1]
    assert result["independent_market_calendar_verified"] is False


def test_replayed_four_middle_buckets_split_structural_clean_runs():
    original = [T + i * 60 for i in range(120)]
    raw = original[:90] + original[15:75] + original[90:]
    result = check(raw, original)
    assert result["stored_complete_m15_buckets_touched_by_repeated_source_minutes"] == 4
    assert result["common_complete_m15_buckets_without_repeated_source_minutes"] == 4
    assert result["common_clean_m15_contiguous_run_count"] == 2
    assert result["common_clean_m15_longest_contiguous_run_buckets"] == 3
    assert [x["complete_m15_buckets"] for x in result["common_clean_m15_contiguous_run_samples"]] == [1, 3]
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_all_buckets_replayed_means_no_clean_runs():
    original = [T + i * 60 for i in range(30)]
    result = check(original + original, original)
    assert result["common_clean_m15_contiguous_run_count"] == 0
    assert result["common_clean_m15_longest_contiguous_run_buckets"] == 0
    assert result["common_clean_m15_contiguous_run_samples"] == []
    assert result["common_clean_complete_m15_set_sha256"]


def test_zero_samples_keeps_complete_counts_and_fingerprints():
    original = [T + i * 60 for i in range(120)]
    raw = original[:90] + original[15:75] + original[90:]
    result = check(raw, original, sample_limit=0)
    assert result["common_clean_m15_contiguous_run_count"] == 2
    assert result["common_clean_m15_longest_contiguous_run_buckets"] == 3
    assert result["common_clean_m15_contiguous_run_samples"] == []
    assert result["stored_replay_touched_complete_m15_set_sha256"] == check(raw, original)["stored_replay_touched_complete_m15_set_sha256"]


def test_repeated_minute_hash_distinguishes_replays_within_same_bucket():
    original = [T + i * 60 for i in range(15)]
    a = check(original + [original[5]], original)
    b = check(original + [original[6]], original)
    assert a["stored_replay_touched_complete_m15_set_sha256"] == b["stored_replay_touched_complete_m15_set_sha256"]
    assert a["source_repeated_minute_set_sha256"] != b["source_repeated_minute_set_sha256"]
    assert a["result"] == b["result"] == "QUARANTINE_REQUIRED"


def test_deterministic_structural_runs_do_not_change_inputs():
    original = [T + i * 60 for i in range(30)]
    raw = original + [original[5]]
    before = raw[:]
    assert check(raw, original) == check(raw, original)
    assert raw == before
