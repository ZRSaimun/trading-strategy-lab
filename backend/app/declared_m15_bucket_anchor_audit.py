"""Read-only fixed-offset M15 bucket identity audit for declared M1 inventories.

Neither input authenticates a vendor, calendar, timestamp convention or price.
No I/O, implicit timezone selection, trading eligibility or execution routes.
"""
from __future__ import annotations

import hashlib
import re

_MAX_ROWS = 100_000
_MAX_UTC_MINUTE = 253402300740
_MAX_OFFSETS = 32
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def _validated_minutes(value: object, name: str, *, increasing: bool) -> list[int]:
    if type(value) is not list or not 1 <= len(value) <= _MAX_ROWS:
        raise ValueError(f"{name}: nonempty bounded list required")
    previous = None
    for minute in value:
        if (type(minute) is not int or minute < 0 or minute > _MAX_UTC_MINUTE
                or minute % 60):
            raise ValueError(f"{name}: invalid UTC-aligned minute label")
        if increasing and previous is not None and minute <= previous:
            raise ValueError(f"{name}: strictly increasing unique minutes required")
        previous = minute
    return value


def _complete_buckets(minutes: set[int]) -> set[int]:
    counts: dict[int, int] = {}
    for minute in minutes:
        start = minute // 900 * 900
        counts[start] = counts.get(start, 0) + 1
    return {start for start, count in counts.items() if count == 15}


def _bucket_sha256(starts: list[int]) -> str:
    digest = hashlib.sha256(b"DECLARED_ANCHOR_MATCHED_CLEAN_M15_BUCKET_STARTS_V1\n")
    for start in starts:
        digest.update(f"{start}\n".encode("ascii"))
    return digest.hexdigest()


def _source_order_complete_buckets(source: list[int]) -> set[int]:
    """Return aligned 15-minute windows contiguous in original source row order.

    This is per-bucket contiguity only; it does not establish global chronology.
    """
    starts: set[int] = set()
    previous = None
    streak = 0
    for minute in source:
        streak = streak + 1 if previous is not None and minute == previous + 60 else 1
        if streak >= 15:
            start = minute - 14 * 60
            if start % 900 == 0:
                starts.add(start)
        previous = minute
    return starts


def _source_order_bucket_sha256(starts: list[int]) -> str:
    digest = hashlib.sha256(b"DECLARED_ANCHOR_SOURCE_ORDER_CLEAN_M15_BUCKET_STARTS_V1\n")
    for start in starts:
        digest.update(f"{start}\n".encode("ascii"))
    return digest.hexdigest()


def audit_declared_m15_bucket_anchors(
    source_wall_minutes: list[int], anchor_utc_minutes: list[int], *,
    source_id: str, offset_candidates_minutes: list[int],
) -> dict:
    """Compare structurally complete, replay-free M15 identities under fixed offsets.

    Source labels are naive wall-clock fields encoded *as if UTC*. Offsets are
    local minus UTC, in whole 15-minute increments. The UTC anchor is a
    caller-declared inventory, NOT an authenticated session calendar.

    Completeness means exactly 15 distinct M1 starts in one aligned bucket;
    replay-free additionally means exactly 15 source rows. This does not
    establish source-order contiguity, a market session or eligible prices.
    """
    if type(source_id) is not str or _ID.fullmatch(source_id) is None:
        raise ValueError("Bounded source identifier required")
    source = _validated_minutes(source_wall_minutes, "source_wall_minutes", increasing=False)
    anchor = _validated_minutes(anchor_utc_minutes, "anchor_utc_minutes", increasing=True)
    offsets = offset_candidates_minutes
    if (type(offsets) is not list or not 1 <= len(offsets) <= _MAX_OFFSETS
            or any(type(o) is not int or o < -840 or o > 840 or o % 15 for o in offsets)
            or len(set(offsets)) != len(offsets)):
        raise ValueError("Distinct bounded fixed 15-minute offsets required")

    source_counts: dict[int, int] = {}
    source_unique: dict[int, set[int]] = {}
    for minute in source:
        start = minute // 900 * 900
        source_counts[start] = source_counts.get(start, 0) + 1
        source_unique.setdefault(start, set()).add(minute)

    clean = {start for start, values in source_unique.items()
             if len(values) == 15 and source_counts[start] == 15}
    complete = {start for start, values in source_unique.items() if len(values) == 15}
    touched = {start for start, values in source_unique.items()
               if source_counts[start] > len(values)}
    # Distinct-minute completeness does not establish source-row chronology.
    # Preserve the original structural population and add a stricter census.
    source_order_clean = clean & _source_order_complete_buckets(source)
    anchor_complete = _complete_buckets(set(anchor))
    candidates = []
    minimum, maximum = min(source), max(source)
    for offset in offsets:
        shift = offset * 60
        if minimum - shift < 0 or maximum - shift > _MAX_UTC_MINUTE:
            raise ValueError("Offset shifts source outside supported UTC range")
        shifted_clean = {start - shift for start in clean}
        matched = sorted(shifted_clean & anchor_complete)
        matched_source_order = sorted(
            {start - shift for start in source_order_clean} & anchor_complete
        )
        candidates.append({
            "declared_local_minus_utc_offset_minutes": offset,
            "anchor_matched_replay_free_complete_m15_buckets": len(matched),
            "source_clean_m15_buckets_outside_complete_anchor": len(clean) - len(matched),
            "anchor_complete_m15_buckets_without_clean_source": len(anchor_complete) - len(matched),
            "anchor_matched_clean_m15_bucket_starts_sha256": _bucket_sha256(matched),
            "anchor_matched_clean_m15_bucket_starts_sample": matched[:8],
            "anchor_matched_source_order_contiguous_clean_m15_buckets": len(matched_source_order),
            "source_order_contiguous_clean_m15_buckets_outside_complete_anchor": (
                len(source_order_clean) - len(matched_source_order)
            ),
            "anchor_matched_source_order_contiguous_clean_m15_bucket_starts_sha256": (
                _source_order_bucket_sha256(matched_source_order)
            ),
            "anchor_matched_source_order_contiguous_clean_m15_bucket_starts_sample": (
                matched_source_order[:8]
            ),
        })

    highest = max(x["anchor_matched_replay_free_complete_m15_buckets"] for x in candidates)
    return {
        "protocol": "declared-fixed-offset-m15-bucket-anchor-audit-v1",
        "source_id": source_id,
        "source_wall_rows": len(source),
        "source_wall_distinct_minutes": sum(map(len, source_unique.values())),
        "source_wall_m15_buckets": len(source_unique),
        "source_wall_complete_m15_buckets": len(complete),
        "source_wall_replay_free_complete_m15_buckets": len(clean),
        "source_order_contiguous_replay_free_complete_m15_buckets": len(source_order_clean),
        "source_wall_replay_free_complete_but_noncontiguous_m15_buckets": (
            len(clean) - len(source_order_clean)
        ),
        "source_wall_replay_touched_m15_buckets": len(touched),
        "source_wall_replay_touched_complete_m15_buckets": len(complete & touched),
        "source_wall_incomplete_m15_buckets": len(source_unique) - len(complete),
        "anchor_utc_minutes": len(anchor),
        "anchor_complete_m15_buckets": len(anchor_complete),
        "candidate_results": candidates,
        "highest_matched_clean_m15_bucket_count": highest,
        "highest_source_order_matched_clean_m15_bucket_count": max(
            x["anchor_matched_source_order_contiguous_clean_m15_buckets"] for x in candidates
        ),
        "highest_match_candidate_count": sum(
            x["anchor_matched_replay_free_complete_m15_buckets"] == highest
            for x in candidates
        ),
        "clock_offset_selected": False,
        "clock_offset_verified": False,
        "anchor_independence_verified": False,
        "source_authenticity_verified": False,
        "market_calendar_verified": False,
        "licensing_verified": False,
        "research_ready": False,
        "live": False,
        "may_execute_order": False,
    }
