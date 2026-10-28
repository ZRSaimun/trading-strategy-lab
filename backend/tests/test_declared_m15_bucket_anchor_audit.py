"""Only synthetic timestamp inventories; no provider or market-data access."""
import pytest

from app.declared_m15_bucket_anchor_audit import audit_declared_m15_bucket_anchors

T = 1_790_000_100
assert T % 900 == 0


def check(source, anchor, offsets=(-300, 0)):
    return audit_declared_m15_bucket_anchors(
        source, anchor, source_id="synthetic:source", offset_candidates_minutes=list(offsets)
    )


def minutes(start, count):
    return [start + i * 60 for i in range(count)]


def test_two_clean_buckets_under_declared_fixed_est_only():
    source = minutes(T, 30)
    anchor = [m + 18000 for m in source]
    report = check(source, anchor)
    assert report["source_wall_complete_m15_buckets"] == 2
    assert report["source_wall_replay_free_complete_m15_buckets"] == 2
    assert report["anchor_complete_m15_buckets"] == 2
    assert [c["anchor_matched_replay_free_complete_m15_buckets"]
            for c in report["candidate_results"]] == [2, 0]
    assert report["candidate_results"][0]["anchor_matched_clean_m15_bucket_starts_sample"] == [T + 18000, T + 18900]
    assert report["clock_offset_selected"] is False
    assert report["research_ready"] is False
    assert report["may_execute_order"] is False


def test_replayed_complete_bucket_excluded_even_with_perfect_anchor():
    source = minutes(T, 30) + [T + 21 * 60]
    anchor = [m + 18000 for m in minutes(T, 30)]
    report = check(source, anchor)
    assert report["source_wall_complete_m15_buckets"] == 2
    assert report["source_wall_replay_touched_m15_buckets"] == 1
    assert report["source_wall_replay_touched_complete_m15_buckets"] == 1
    assert report["source_wall_replay_free_complete_m15_buckets"] == 1
    assert report["candidate_results"][0]["anchor_matched_replay_free_complete_m15_buckets"] == 1
    assert report["candidate_results"][0]["anchor_complete_m15_buckets_without_clean_source"] == 1


def test_partial_bucket_with_duplicate_is_not_complete():
    source = minutes(T, 14) + [T + 3 * 60]
    report = check(source, minutes(T, 15), (0,))
    assert report["source_wall_complete_m15_buckets"] == 0
    assert report["source_wall_replay_touched_m15_buckets"] == 1
    assert report["source_wall_replay_touched_complete_m15_buckets"] == 0
    assert report["source_wall_incomplete_m15_buckets"] == 1
    assert report["candidate_results"][0]["anchor_matched_replay_free_complete_m15_buckets"] == 0


def test_anchor_partial_does_not_claim_complete_bucket():
    report = check(minutes(T, 15), minutes(T, 14), (0,))
    assert report["source_wall_replay_free_complete_m15_buckets"] == 1
    assert report["anchor_complete_m15_buckets"] == 0
    assert report["candidate_results"][0]["source_clean_m15_buckets_outside_complete_anchor"] == 1


def test_nonadjacent_replay_and_unsorted_source_are_quarantined():
    source = minutes(T, 30)
    source = source[15:] + source[:15] + [T]
    report = check(source, minutes(T, 30), (0,))
    assert report["source_wall_replay_touched_complete_m15_buckets"] == 1
    assert report["candidate_results"][0]["anchor_matched_replay_free_complete_m15_buckets"] == 1


def test_same_count_wrong_bucket_id_does_not_match():
    report = check(minutes(T, 15), minutes(T + 900, 15), (0,))
    assert report["anchor_complete_m15_buckets"] == 1
    assert report["candidate_results"][0]["anchor_matched_replay_free_complete_m15_buckets"] == 0


def test_tied_offset_candidates_do_not_select_clock():
    anchor = minutes(T, 15) + minutes(T + 18000, 15)
    report = check(minutes(T, 15), anchor, (-300, 0))
    assert report["highest_match_candidate_count"] == 2
    assert report["clock_offset_verified"] is False


def test_fingerprint_deterministic_and_caller_inputs_unchanged():
    source = minutes(T, 15)
    anchor = minutes(T, 15)
    before = (source[:], anchor[:])
    a, b = check(source, anchor, (0,)), check(source, anchor, (0,))
    assert a == b
    assert (source, anchor) == before
    assert len(a["candidate_results"][0]["anchor_matched_clean_m15_bucket_starts_sha256"]) == 64
    assert a["candidate_results"][0]["anchor_matched_clean_m15_bucket_starts_sha256"] != check(source, minutes(T+900, 15), (0,))["candidate_results"][0]["anchor_matched_clean_m15_bucket_starts_sha256"]


def test_bounded_samples():
    report = check(minutes(T, 15 * 20), minutes(T, 15 * 20), (0,))
    assert report["candidate_results"][0]["anchor_matched_replay_free_complete_m15_buckets"] == 20
    assert len(report["candidate_results"][0]["anchor_matched_clean_m15_bucket_starts_sample"]) == 8


@pytest.mark.parametrize("offsets", [[], [True], [0, 0], [1], [841], [-841], [0.0], ["0"], None, list(range(33))])
def test_invalid_offsets_rejected(offsets):
    with pytest.raises(ValueError):
        check([T], [T], offsets) if offsets is not None else audit_declared_m15_bucket_anchors([T], [T], source_id="synthetic", offset_candidates_minutes=None)


@pytest.mark.parametrize("source,anchor", [([], [T]), ([T], []), ([True], [T]), ([T], [False]), ([T+1], [T]), ([T], [T+1]), ([T], [T, T]), ([T], [T+60, T]), ([float(T)], [T])])
def test_invalid_timestamp_lists_rejected(source, anchor):
    with pytest.raises(ValueError):
        check(source, anchor, (0,))


def test_offset_underflow_and_overflow_rejected():
    with pytest.raises(ValueError):
        check([0], [0], (15,))
    with pytest.raises(ValueError):
        check([253402300740], [253402300740], (-15,))


def test_invalid_source_identifier_rejected():
    with pytest.raises(ValueError):
        audit_declared_m15_bucket_anchors([T], [T], source_id="../\n", offset_candidates_minutes=[0])
