"""Synthetic tests; no real provider timestamps or vendor calls."""
import pytest

from app.source_wall_clock_offset_audit import audit_declared_clock_offsets

T = 1_790_000_100
assert T % 60 == 0


def audit(wall, anchor, offsets):
    return audit_declared_clock_offsets(
        wall, anchor, source_id="synthetic:clock", offset_candidates_minutes=offsets
    )


def test_declared_fixed_est_matches_only_matching_anchor():
    wall = [T + i * 60 for i in range(4)]
    anchor = [x + 300 * 60 for x in wall]
    result = audit(wall, anchor, [-300, -240, 0])
    assert [x["matched_distinct_anchor_minutes"] for x in result["candidate_results"]] == [4, 0, 0]
    assert result["candidate_results"][0]["anchor_overlap_basis_points"] == 10000
    assert result["highest_overlap_candidate_count"] == 1
    assert result["clock_offset_selected"] is False
    assert result["clock_offset_verified"] is False
    assert result["research_ready"] is False
    assert result["may_execute_order"] is False


def test_replays_and_backward_source_rows_do_not_inflate_overlap():
    result = audit([T + 60, T, T, T + 120], [T, T + 60, T + 120], [0])
    assert result["source_wall_rows"] == 4
    assert result["source_wall_distinct_minutes"] == 3
    assert result["source_wall_repeated_rows"] == 1
    assert result["source_wall_backward_jumps"] == 1
    assert result["candidate_results"][0]["matched_distinct_anchor_minutes"] == 3


def test_equal_overlap_is_not_clock_proof():
    wall = [T, T + 60]
    anchor = sorted(wall + [x + 300 * 60 for x in wall])
    result = audit(wall, anchor, [-300, 0])
    assert result["highest_overlap_candidate_count"] == 2
    assert result["highest_declared_overlap_count"] == 2
    assert result["clock_offset_selected"] is False
    assert result["anchor_independence_verified"] is False


def test_deterministic_hashes_and_caller_lists_unchanged():
    wall = [T, T + 60]
    anchor = [T + 300 * 60, T + 301 * 60]
    before = (wall[:], anchor[:])
    assert audit(wall, anchor, [-300]) == audit(wall, anchor, [-300])
    assert (wall, anchor) == before


@pytest.mark.parametrize("offsets", [[], [True], [0, 0], [841], [-841], [1], [15.0], ["-300"], None, list(range(0, 33))])
def test_invalid_offset_candidates_fail_closed(offsets):
    with pytest.raises(ValueError):
        audit([T], [T], offsets)


@pytest.mark.parametrize("wall,anchor", [([], [T]), ([T], []), ([True], [T]), ([T], [False]), ([T + 1], [T]), ([T], [T + 1]), ([T], [T, T]), ([T], [T + 60, T]), ([float(T)], [T])])
def test_invalid_minute_lists_fail_closed(wall, anchor):
    with pytest.raises(ValueError):
        audit(wall, anchor, [0])


def test_offset_underflow_and_overflow_fail_closed():
    with pytest.raises(ValueError):
        audit([0], [0], [15])
    with pytest.raises(ValueError):
        audit([253402300740], [253402300740], [-15])


def test_bad_source_id_fails_closed():
    with pytest.raises(ValueError):
        audit_declared_clock_offsets([T], [T], source_id="../../\n", offset_candidates_minutes=[0])
