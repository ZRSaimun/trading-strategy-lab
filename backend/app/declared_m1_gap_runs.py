"""Offline, bounded missing-minute run audit against an explicit UTC session manifest.

No provider calls, calendars, storage, price repair, orders or live-feed claims.
A declared session is not an independently authenticated market calendar.
"""
from __future__ import annotations

from collections import Counter

from .expected_bar_manifest import ExpectedM1Manifest, compile_expected_m1_manifest

_MAX_ROWS = 20_000


def audit_declared_m1_gap_runs(
    manifest: ExpectedM1Manifest, observed_minutes: list[int], *, sample_limit: int = 20,
) -> dict:
    """Count missing contiguous M1 runs, respecting session and closure boundaries.

    Input timestamps are bar STARTS in UTC seconds. A gap is only an absent
    *declared expected* minute, not proof that a market was open or a vendor
    failed. Duplicates, backward timestamp transitions and unexpected
    observations are flagged, never repaired. Input order is preserved.
    """
    if type(manifest) is not ExpectedM1Manifest:
        raise ValueError("Compiled expected-bar manifest required")
    rebuilt = compile_expected_m1_manifest(
        provider=manifest.provider, symbol=manifest.symbol,
        venue=manifest.venue, price_side=manifest.price_side,
        calendar_id=manifest.calendar_id,
        calendar_revision=manifest.calendar_revision,
        calendar_source=manifest.calendar_source,
        observed_at_utc=manifest.observed_at_utc,
        sessions_utc=list(manifest.sessions_utc),
        exclusions_utc=list(manifest.exclusions_utc),
    )
    if rebuilt != manifest:
        raise ValueError("Expected-bar manifest mutated")
    if (type(observed_minutes) is not list or len(observed_minutes) > _MAX_ROWS
            or type(sample_limit) is not int or not 0 <= sample_limit <= 50):
        raise ValueError("Bounded observation list and sample limit required")
    seen: set[int] = set()
    duplicate_rows = 0
    backward_transitions = 0
    backward_samples: list[dict[str, int]] = []
    previous_stamp: int | None = None
    for stamp in observed_minutes:
        if (type(stamp) is not int or stamp < 0 or stamp % 60
                or stamp + 60 > manifest.observed_at_utc):
            raise ValueError("Invalid or unfinished UTC observation")
        if previous_stamp is not None and stamp < previous_stamp:
            backward_transitions += 1
            if len(backward_samples) < sample_limit:
                backward_samples.append({"previous_utc": previous_stamp, "observed_utc": stamp})
        previous_stamp = stamp
        if stamp in seen:
            duplicate_rows += 1
        seen.add(stamp)

    expected = set(manifest.expected_minutes)
    unexpected = seen - expected
    exclusions = {t for start, end in manifest.exclusions_utc for t in range(start, end, 60)}
    # Keep closure-minute observations distinct from observations outside all
    # declared sessions. Neither category authenticates a market calendar.
    observed_in_exclusions = unexpected & exclusions
    observed_outside_sessions = unexpected - observed_in_exclusions
    if len(observed_in_exclusions) + len(observed_outside_sessions) != len(unexpected):
        raise ValueError("Unexpected-minute attribution failed")
    runs: list[tuple[int, int]] = []
    for start, end in manifest.sessions_utc:
        run_start = None
        run_length = 0
        for minute in range(start, end, 60):
            if minute in exclusions or minute in seen:
                if run_start is not None:
                    runs.append((run_start, run_length))
                    run_start = None
                    run_length = 0
            else:
                if run_start is None:
                    run_start = minute
                run_length += 1
        if run_start is not None:
            runs.append((run_start, run_length))
    missing = sum(length for _, length in runs)
    if missing != len(expected - seen):
        raise ValueError("Expected-minute gap reconciliation failed")
    lengths = Counter(length for _, length in runs)
    return {
        "status": ("DECLARED_COVERAGE_COMPLETE_UNVERIFIED" if not (missing or duplicate_rows or unexpected or backward_transitions)
                   else "REVIEW_REQUIRED"),
        "calendar_manifest_sha256": manifest.manifest_sha256,
        "provider": manifest.provider,
        "symbol": manifest.symbol,
        "price_side": manifest.price_side,
        "expected_minutes": len(expected),
        "unique_observed_expected_minutes": len(expected & seen),
        "missing_expected_minutes": missing,
        "missing_gap_runs": len(runs),
        "longest_missing_gap_minutes": max((length for _, length in runs), default=0),
        "gap_run_length_histogram": {str(k): lengths[k] for k in sorted(lengths)},
        "missing_gap_samples": [
            {"start_utc": start, "end_exclusive_utc": start + 60 * length,
             "minutes": length} for start, length in runs[:sample_limit]
        ],
        "duplicate_observation_rows": duplicate_rows,
        "backward_timestamp_transitions": backward_transitions,
        "backward_timestamp_samples": backward_samples,
        "unexpected_unique_minutes": len(unexpected),
        "unexpected_minute_samples": sorted(unexpected)[:sample_limit],
        "observed_in_declared_exclusions_unique_minutes": len(observed_in_exclusions),
        "observed_outside_declared_sessions_unique_minutes": len(observed_outside_sessions),
        "observed_in_declared_exclusions_samples": sorted(observed_in_exclusions)[:sample_limit],
        "observed_outside_declared_sessions_samples": sorted(observed_outside_sessions)[:sample_limit],
        "declared_excluded_minutes": len(exclusions),
        "declared_session_intervals": len(manifest.sessions_utc),
        "expected_calendar_verified": False,
        "source_authenticated": False,
        "data_rights_verified": False,
        "live": False,
        "may_execute_order": False,
    }
