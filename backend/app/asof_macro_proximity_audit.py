"""Read-only, as-of scheduled macro-event proximity audit for frozen M1 intents.

This is a *descriptive* metadata diagnostic, never a signal filter or broker
safety gate. A self-declared event publication clock is not independently
authenticated and a retrospective calendar cannot prove historical coverage.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import hashlib
import json
import re

from app.frozen_next_open_intent import fingerprint_next_open_intents

_PROTOCOL = "frozen-scheduled-macro-calendar-v1"
_REPORT = "frozen-intent-asof-macro-proximity-v1"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK = 8640000000
_MAX_EVENTS = 100000
_WINDOWS_MINUTES = (15, 60)


def _exact(obj, fields, label):
    if not isinstance(obj, dict) or set(obj) != set(fields):
        raise ValueError(f"{label} must have exactly the specified fields")


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_CLOCK and value % 60 == 0


def _validate_calendar(calendar):
    _exact(calendar, ("protocol", "source", "events"), "Calendar")
    if calendar["protocol"] != _PROTOCOL:
        raise ValueError("Unknown calendar protocol")
    source = calendar["source"]
    _exact(source, ("provider", "instrument", "snapshot_id"), "Calendar source")
    for key in source:
        if not isinstance(source[key], str) or not _ID.fullmatch(source[key]):
            raise ValueError("Invalid calendar source identity")
    events = calendar["events"]
    if not isinstance(events, list) or len(events) > _MAX_EVENTS:
        raise ValueError("Invalid bounded calendar event population")
    ids = set()
    for event in events:
        _exact(event, ("event_id", "scheduled_at", "known_at", "impact"), "Event")
        if not isinstance(event["event_id"], str) or not _ID.fullmatch(event["event_id"]):
            raise ValueError("Invalid calendar event ID")
        if event["event_id"] in ids:
            raise ValueError("Duplicate calendar event ID")
        ids.add(event["event_id"])
        if not _clock(event["scheduled_at"]) or not _clock(event["known_at"]):
            raise ValueError("Invalid UTC minute event clock")
        if event["impact"] not in ("HIGH", "MEDIUM", "LOW"):
            raise ValueError("Unknown declared impact tier")
    return events


def fingerprint_scheduled_macro_calendar(calendar):
    """Order-independent consistency hash, NOT authenticated publication proof."""
    events = _validate_calendar(calendar)
    canonical = dict(protocol=_PROTOCOL, source=calendar["source"],
                     events=sorted(events, key=lambda e: (e["scheduled_at"], e["event_id"])))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Fenwick:
    def __init__(self, size):
        self.tree = [0] * (size + 1)

    def add(self, index, amount=1):
        index += 1
        while index < len(self.tree):
            self.tree[index] += amount
            index += index & -index

    def prefix(self, end):
        total = 0
        while end:
            total += self.tree[end]
            end -= end & -end
        return total

    def between(self, left, right):
        return self.prefix(right) - self.prefix(left)


def audit_asof_macro_proximity(manifest, expected_manifest_sha256, calendar,
                               expected_calendar_sha256, *, sample_limit=20):
    """Count known-at-signal events without using later revisions or surprises.

    A scheduled event is only counted as *known* when the exact supplied
    event-version known_at is <= the completed signal close. Later-known
    events are separately marked unknown-as-of; never inferred absent.
    Two fixed, non-optimized inclusive windows are reported: +/-15 and
    +/-60 minutes. No actual/forecast/released economic values are accepted.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid sample limit")
    if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
        raise ValueError("Expected manifest SHA-256 required")
    if not isinstance(expected_calendar_sha256, str) or not _SHA.fullmatch(expected_calendar_sha256):
        raise ValueError("Expected calendar SHA-256 required")
    manifest_digest = fingerprint_next_open_intents(manifest)
    if manifest_digest != expected_manifest_sha256:
        raise ValueError("Frozen intent fingerprint mismatch")
    calendar_digest = fingerprint_scheduled_macro_calendar(calendar)
    if calendar_digest != expected_calendar_sha256:
        raise ValueError("Calendar fingerprint mismatch")
    if manifest["source"]["instrument"] != calendar["source"]["instrument"]:
        raise ValueError("Calendar and intent instrument mismatch")

    events = calendar["events"]
    times = sorted({event["scheduled_at"] for event in events})
    all_times = sorted(event["scheduled_at"] for event in events)
    by_known = sorted(events, key=lambda e: (e["known_at"], e["scheduled_at"], e["event_id"]))
    eligible = sorted(manifest["eligible_intents"], key=lambda x: (x["signal_at"], x["path_id"]))
    known_all, known_high = _Fenwick(len(times)), _Fenwick(len(times))
    stats = {
        window: dict(signals_with_known_high=0, signals_with_known_any=0,
                     signals_with_later_known_event=0, signals_without_declared_event=0,
                     known_event_observations=0, known_high_event_observations=0,
                     later_known_event_observations=0)
        for window in _WINDOWS_MINUTES
    }
    samples = []
    event_index = 0
    for intent in eligible:
        at = intent["signal_at"]
        while event_index < len(by_known) and by_known[event_index]["known_at"] <= at:
            event = by_known[event_index]
            position = bisect_left(times, event["scheduled_at"])
            known_all.add(position)
            if event["impact"] == "HIGH":
                known_high.add(position)
            event_index += 1
        sample = dict(path_id=intent["path_id"], signal_at=at, windows=[])
        for window in _WINDOWS_MINUTES:
            delta = window * 60
            lo, hi = bisect_left(times, at - delta), bisect_right(times, at + delta)
            known = known_all.between(lo, hi)
            high = known_high.between(lo, hi)
            declared = (bisect_right(all_times, at + delta)
                        - bisect_left(all_times, at - delta))
            later = declared - known
            row = stats[window]
            row["signals_with_known_high"] += high > 0
            row["signals_with_known_any"] += known > 0
            row["signals_with_later_known_event"] += later > 0
            row["signals_without_declared_event"] += declared == 0
            row["known_event_observations"] += known
            row["known_high_event_observations"] += high
            row["later_known_event_observations"] += later
            if len(samples) < sample_limit:
                sample["windows"].append(dict(minutes=window, known_events=known,
                                              known_high_events=high,
                                              later_known_events=later))
        if len(samples) < sample_limit:
            samples.append(sample)
    return dict(
        protocol=_REPORT, manifest_sha256=manifest_digest,
        calendar_sha256=calendar_digest,
        calendar_source=dict(calendar["source"]),
        eligible_intents=len(eligible),
        declared_pre_signal_exclusions=len(manifest["excluded_signals"]),
        declared_calendar_events=len(events),
        windows=[dict(minutes=window, **stats[window]) for window in _WINDOWS_MINUTES],
        sample_limit=sample_limit, intent_samples=samples,
        complete_against_supplied_intent_manifest=True,
        complete_against_supplied_calendar=True,
        independent_calendar_completeness_verified=False,
        independent_publication_clocks_verified=False,
        independent_preregistration_verified=False,
        no_future_event_version_used=True,
        safe_to_trade=False, may_exclude_signals=False, may_execute_order=False,
        verified_profitability=False,
        warning=("Calendar contents, event versions, impact tiers and known_at clocks are "
                 "self-declared. An absent or later-known event does not establish an "
                 "event-free market. This audit is not a historical blackout filter, "
                 "broker safety gate, untouched holdout, or profitability test."),
    )
