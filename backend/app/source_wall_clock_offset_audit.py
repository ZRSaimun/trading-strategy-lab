"""Offline comparison of explicitly declared fixed wall-clock offset hypotheses.

Inputs are caller-encoded minute labels and an independently supplied UTC
inventory. Overlap is not clock authentication or a DST conversion policy.
"""
from __future__ import annotations

import hashlib
import re

MAX_ROWS = 100_000
MAX_CANDIDATES = 32
MAX_UTC_MINUTE = 253402300740
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def _minutes(value: object, label: str, *, ordered: bool) -> list[int]:
    if type(value) is not list or not 1 <= len(value) <= MAX_ROWS:
        raise ValueError(f"{label} must be a nonempty bounded list")
    previous = None
    for minute in value:
        if (type(minute) is not int or not 0 <= minute <= MAX_UTC_MINUTE
                or minute % 60):
            raise ValueError(f"{label} contains invalid minute labels")
        if ordered and previous is not None and minute <= previous:
            raise ValueError(f"{label} must be strictly increasing and unique")
        previous = minute
    return value


def _digest(values: list[int], scope: str) -> str:
    h = hashlib.sha256((scope + "\n").encode("ascii"))
    for value in values:
        h.update(f"{value}\n".encode("ascii"))
    return h.hexdigest()


def audit_declared_clock_offsets(
    source_wall_minutes: list[int], anchor_utc_minutes: list[int], *,
    source_id: str, offset_candidates_minutes: list[int],
) -> dict:
    """Compare fixed offsets without selecting, certifying, or applying one.

    A source wall minute is encoded as the epoch that its *naive* wall-clock
    fields would have if interpreted as UTC. A candidate offset is local-UTC:
    for example, -300 means UTC = wall + 300 minutes. This does not handle
    DST-local ambiguous/nonexistent times; the caller must verify timebase.
    """
    if type(source_id) is not str or _ID.fullmatch(source_id) is None:
        raise ValueError("A bounded source_id is required")
    source = _minutes(source_wall_minutes, "source_wall_minutes", ordered=False)
    anchor = _minutes(anchor_utc_minutes, "anchor_utc_minutes", ordered=True)
    offsets = offset_candidates_minutes
    if (type(offsets) is not list or not 1 <= len(offsets) <= MAX_CANDIDATES
            or any(type(o) is not int or o < -840 or o > 840 or o % 15 for o in offsets)
            or len(set(offsets)) != len(offsets)):
        raise ValueError("Explicit distinct bounded 15-minute offset candidates required")

    source_set = set(source)
    repeated = len(source) - len(source_set)
    backward = sum(b < a for a, b in zip(source, source[1:]))
    anchor_set = set(anchor)
    candidates = []
    for offset in offsets:
        shift = offset * 60
        shifted = set()
        for minute in source_set:
            utc_minute = minute - shift
            if not 0 <= utc_minute <= MAX_UTC_MINUTE:
                raise ValueError("Candidate offset shifts a minute outside supported UTC range")
            shifted.add(utc_minute)
        matched_set = sorted(shifted & anchor_set)
        matched = len(matched_set)
        candidates.append({
            "declared_local_minus_utc_offset_minutes": offset,
            "matched_distinct_anchor_minutes": matched,
            "anchor_minutes_not_matched": len(anchor) - matched,
            "shifted_source_minutes_outside_anchor": len(shifted) - matched,
            "anchor_overlap_basis_points": matched * 10_000 // len(anchor),
            "matched_utc_minute_set_sha256": _digest(matched_set, "DECLARED_CLOCK_MATCH_SET_V1"),
        })
    best_count = max(c["matched_distinct_anchor_minutes"] for c in candidates)
    return {
        "assessment": "DECLARED_FIXED_OFFSET_HYPOTHESES_ONLY",
        "source_id": source_id,
        "source_wall_rows": len(source),
        "source_wall_distinct_minutes": len(source_set),
        "source_wall_repeated_rows": repeated,
        "source_wall_backward_jumps": backward,
        "anchor_utc_distinct_minutes": len(anchor),
        "source_wall_order_sha256": _digest(source, "SOURCE_WALL_ORDER_M1_V1"),
        "anchor_utc_set_sha256": _digest(anchor, "DECLARED_UTC_ANCHOR_M1_V1"),
        "candidate_results": candidates,
        "highest_declared_overlap_count": best_count,
        "highest_overlap_candidate_count": sum(
            c["matched_distinct_anchor_minutes"] == best_count for c in candidates
        ),
        "clock_offset_selected": False,
        "clock_offset_verified": False,
        "anchor_independence_verified": False,
        "dst_transition_verified": False,
        "source_authenticity_verified": False,
        "market_calendar_verified": False,
        "licensing_verified": False,
        "research_ready": False,
        "live": False,
        "may_execute_order": False,
    }
