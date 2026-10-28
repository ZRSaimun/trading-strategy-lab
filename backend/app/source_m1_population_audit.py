"""Offline source-order M1 versus stored unique-minute population preflight.

This timestamp-only audit never opens archives, queries a database, chooses
prices, authenticates a provider, or changes research eligibility. It exposes
population differences hidden by de-duplication of source rows.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

MAX_ROWS = 1_000_000
MAX_UTC_MINUTE = 253402300740  # 9999-12-31 23:59:00 UTC


def _validated(value: object, label: str, *, require_sorted_unique: bool) -> list[int]:
    if type(value) is not list or len(value) > MAX_ROWS or not value:
        raise ValueError(f"{label} must be a nonempty bounded UTC M1 list")
    previous = None
    for minute in value:
        if type(minute) is not int or minute < 0 or minute > MAX_UTC_MINUTE or minute % 60:
            raise ValueError(f"{label} contains an invalid UTC M1 epoch")
        if require_sorted_unique and previous is not None and minute <= previous:
            raise ValueError(f"{label} must be strictly increasing and unique")
        previous = minute
    return value


def _fingerprint(minutes: list[int], *, scope: str) -> str:
    digest = hashlib.sha256((scope + "\n").encode("ascii"))
    for minute in minutes:
        digest.update(f"{minute}\n".encode("ascii"))
    return digest.hexdigest()


def _m15_windows(minutes: list[int]) -> tuple[int, int, int, list[int]]:
    """Count source-order contiguous 15-row UTC-quarter-hour windows.

    This is a *structural* window census, not an OHLC aggregation or proof of
    complete exchange sessions. Repeated windows are counted separately.
    """
    complete = 0
    bucket_counts: dict[int, int] = {}
    start = previous = None
    length = 0
    for minute in minutes:
        if length and minute == previous + 60:
            length += 1
        elif minute % 900 == 0:
            start = minute
            length = 1
        else:
            start = None
            length = 0
        previous = minute
        if length == 15:
            complete += 1
            bucket_counts[start] = bucket_counts.get(start, 0) + 1
            start = None
            length = 0
    repeats = sum(count - 1 for count in bucket_counts.values())
    return complete, len(bucket_counts), repeats, sorted(
        bucket for bucket, count in bucket_counts.items() if count > 1
    ), set(bucket_counts)


def _iso(minute: int) -> str:
    return datetime.fromtimestamp(minute, timezone.utc).isoformat()


def audit_source_m1_population(
    source_order_minutes: list[int], stored_minutes: list[int], *,
    source_id: str, sample_limit: int = 5,
) -> dict:
    """Compare raw row-order and stored unique timestamp populations.

    The caller must independently verify ZIP identity, parser, UTC conversion,
    and the read-only database snapshot. Matching minutes cannot prove price
    parity, provider authenticity, licensing or executable market quotes.
    """
    if type(source_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", source_id) is None:
        raise ValueError("A bounded source identifier is required")
    if type(sample_limit) is not int or not 0 <= sample_limit <= 20:
        raise ValueError("sample_limit must be an integer from 0 to 20")
    source = _validated(source_order_minutes, "source_order_minutes", require_sorted_unique=False)
    stored = _validated(stored_minutes, "stored_minutes", require_sorted_unique=True)

    seen: set[int] = set()
    repeated_minutes: set[int] = set()
    repeats = backward = adjacent = 0
    first_repeat_ordinal = last_repeat_ordinal = None
    repeat_samples: list[dict] = []
    repeated_run_count = longest_repeated_run = 0
    repeated_run_samples: list[dict] = []
    run_start = run_end = run_first_minute = run_last_minute = None
    previous = None
    for ordinal, minute in enumerate(source, 1):
        if previous is not None:
            if minute < previous:
                backward += 1
            elif minute == previous:
                adjacent += 1
        if minute in seen:
            repeated_minutes.add(minute)
            repeats += 1
            if first_repeat_ordinal is None:
                first_repeat_ordinal = ordinal
            last_repeat_ordinal = ordinal
            if len(repeat_samples) < sample_limit:
                repeat_samples.append({"row_ordinal": ordinal, "minute_utc": _iso(minute)})
            if run_start is None:
                run_start, run_first_minute = ordinal, minute
            run_end, run_last_minute = ordinal, minute
        else:
            if run_start is not None:
                repeated_run_count += 1
                longest_repeated_run = max(longest_repeated_run, run_end - run_start + 1)
                if len(repeated_run_samples) < sample_limit:
                    repeated_run_samples.append({
                        "first_row_ordinal": run_start,
                        "last_row_ordinal": run_end,
                        "repeated_rows": run_end - run_start + 1,
                        "first_minute_utc": _iso(run_first_minute),
                        "last_minute_utc": _iso(run_last_minute),
                    })
                run_start = None
            seen.add(minute)
        previous = minute
    if run_start is not None:
        repeated_run_count += 1
        longest_repeated_run = max(longest_repeated_run, run_end - run_start + 1)
        if len(repeated_run_samples) < sample_limit:
            repeated_run_samples.append({
                "first_row_ordinal": run_start,
                "last_row_ordinal": run_end,
                "repeated_rows": run_end - run_start + 1,
                "first_minute_utc": _iso(run_first_minute),
                "last_minute_utc": _iso(run_last_minute),
            })

    stored_set = set(stored)
    missing = sorted(seen - stored_set)
    extra = sorted(stored_set - seen)
    raw_m15, raw_distinct, raw_repeat_windows, repeat_buckets, raw_buckets = _m15_windows(source)
    stored_m15, stored_distinct, _, _, stored_buckets = _m15_windows(stored)
    # A repeated source minute contaminates its entire UTC M15 bucket even if
    # its duplicate appears far away in source order and has identical OHLC.
    # Count only *complete stored* buckets; incomplete buckets are not candidates.
    repeated_bucket_starts = {minute - minute % 900 for minute in repeated_minutes}
    stored_replay_touched = sorted(stored_buckets & repeated_bucket_starts)
    raw_only_buckets = sorted(raw_buckets - stored_buckets)
    stored_only_buckets = sorted(stored_buckets - raw_buckets)
    common_without_repeats = (raw_buckets & stored_buckets) - repeated_bucket_starts
    quarantine = bool(
        repeats or backward or missing or extra or raw_m15 != stored_m15
        or raw_only_buckets or stored_only_buckets
    )
    return {
        "result": "QUARANTINE_REQUIRED" if quarantine else "STRUCTURAL_PARITY_ONLY_UNVERIFIED",
        "source_id": source_id,
        "source_order_sha256": _fingerprint(source, scope="SOURCE_ORDER_M1_V1"),
        "stored_unique_sha256": _fingerprint(stored, scope="STORED_UNIQUE_M1_V1"),
        "fingerprint_scope": "caller-provided UTC M1 epochs only, not original ZIP bytes or database signature",
        "source_rows": len(source),
        "source_distinct_minutes": len(seen),
        "stored_distinct_minutes": len(stored),
        "source_repeated_rows": repeats,
        "source_adjacent_equal_timestamps": adjacent,
        "source_backward_timestamp_jumps": backward,
        "first_repeat_row_ordinal": first_repeat_ordinal,
        "last_repeat_row_ordinal": last_repeat_ordinal,
        "source_repeated_row_samples": repeat_samples,
        "source_repeated_row_run_count": repeated_run_count,
        "source_longest_repeated_row_run": longest_repeated_run,
        "source_repeated_row_run_samples": repeated_run_samples,
        "source_unique_missing_from_store": len(missing),
        "stored_minutes_absent_from_source": len(extra),
        "source_missing_from_store_samples_utc": [_iso(t) for t in missing[:sample_limit]],
        "stored_absent_from_source_samples_utc": [_iso(t) for t in extra[:sample_limit]],
        "source_order_complete_m15_windows": raw_m15,
        "source_order_distinct_complete_m15_buckets": raw_distinct,
        "source_order_repeated_complete_m15_windows": raw_repeat_windows,
        "source_order_repeated_m15_bucket_samples_utc": [_iso(t) for t in repeat_buckets[:sample_limit]],
        "stored_complete_m15_windows": stored_m15,
        "stored_distinct_complete_m15_buckets": stored_distinct,
        "source_minus_stored_complete_m15_windows": raw_m15 - stored_m15,
        "source_complete_m15_buckets_absent_from_store": len(raw_only_buckets),
        "stored_complete_m15_buckets_absent_from_source_order": len(stored_only_buckets),
        "source_complete_m15_absent_from_store_samples_utc": [_iso(t) for t in raw_only_buckets[:sample_limit]],
        "stored_complete_m15_absent_from_source_samples_utc": [_iso(t) for t in stored_only_buckets[:sample_limit]],
        "stored_complete_m15_buckets_touched_by_repeated_source_minutes": len(stored_replay_touched),
        "stored_complete_m15_replayed_source_bucket_samples_utc": [_iso(t) for t in stored_replay_touched[:sample_limit]],
        "common_complete_m15_buckets_without_repeated_source_minutes": len(common_without_repeats),
        "m15_bucket_diagnostics_are_not_research_approval": True,
        "timestamp_population_only": True,
        "source_clock_verified": False,
        "original_archive_authenticated": False,
        "price_tuple_parity_verified": False,
        "independent_market_calendar_verified": False,
        "licensing_verified": False,
        "research_ready": False,
        "live": False,
        "may_execute_order": False,
    }
