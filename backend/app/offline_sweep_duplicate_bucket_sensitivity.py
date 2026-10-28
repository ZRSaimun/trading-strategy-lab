"""Offline declared duplicate-minute M15 quarantine sensitivity for frozen sweeps.

Preserves original bar count and 70/30 split index. Does not authenticate
source minutes, verify broker fills, or authorize orders.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .offline_sweep_probe import Bar, research

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BARS = 500_000
_MAX_DUPLICATES = 100_000
_MAX_INPUT_BYTES = 128 * 1024 * 1024
_STEP = timedelta(minutes=15)


def _quarter_hour(stamp):
    return stamp.replace(minute=(stamp.minute // 15) * 15, second=0, microsecond=0)


def _parse_clock(value, *, quarter=False):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00", value):
        raise ValueError("Expected source-local ISO minute timestamp without timezone")
    stamp = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    if quarter and stamp.minute % 15:
        raise ValueError("M15 bar timestamp must align to quarter hour")
    return stamp


def _summary(report):
    return {
        name: {
            "confirmed": cell["confirmed_signals"],
            "entered": cell["entered_positions"],
            "observed": cell["observed_outcomes"],
            "censored": cell["censored_due_to_gaps_or_boundaries"],
            "missing_entry": cell["confirmed_signals_without_observable_entry"],
            "cost_scenarios": [
                {"extra_bps": c["additional_round_trip_bps"],
                 "observed_count": c["count"],
                 "observed_mean_net_r": c["mean_net_r"]}
                for c in cell["cost_scenarios"]
            ],
        }
        for name, cell in report["cohorts"].items()
    }


def audit_declared_duplicate_minutes(bars, duplicate_m1_times, *, dataset_id, archive_sha256):
    """Compare original research with duplicate-bucket-isolated sensitivity.

    Duplicate timestamps are caller declarations, not authenticated source.
    Each touched M15 bar is isolated as a singleton segment; safe runs after
    contamination also start new segments. No bar or split index is removed.
    This is NOT a matched-trade causal estimate.
    """
    if any(not isinstance(s, str) or not _SHA.fullmatch(s)
           for s in (dataset_id, archive_sha256)):
        raise ValueError("Explicit lowercase dataset and original ZIP SHA-256 required")
    if not isinstance(bars, (tuple, list)) or not 1 <= len(bars) <= _MAX_BARS:
        raise ValueError("Bounded nonempty M15 population required")
    if not isinstance(duplicate_m1_times, (tuple, list)) or len(duplicate_m1_times) > _MAX_DUPLICATES:
        raise ValueError("Bounded duplicate-minute census required")
    previous = None
    for bar in bars:
        if (not isinstance(bar, Bar) or type(bar.time) is not datetime or
                bar.time.tzinfo is not None or bar.time.second or bar.time.microsecond or
                bar.time.minute % 15 or type(bar.segment) is not int):
            raise ValueError("Invalid source-local M15 bar identity")
        if previous is not None and bar.time <= previous:
            raise ValueError("M15 bars must be strictly chronological")
        if not all(isinstance(v, Decimal) and v.is_finite() and v > 0
                   for v in (bar.o, bar.h, bar.l, bar.c)) or (
                bar.h < max(bar.o, bar.c) or bar.l > min(bar.o, bar.c)):
            raise ValueError("Invalid Decimal OHLC geometry")
        previous = bar.time
    duplicates = []
    previous = None
    for value in duplicate_m1_times:
        stamp = _parse_clock(value)
        if previous is not None and stamp <= previous:
            raise ValueError("Duplicate-minute declaration must be unique and sorted")
        duplicates.append(stamp)
        previous = stamp
    touched = {_quarter_hour(stamp) for stamp in duplicates}
    present = {bar.time for bar in bars}
    matched = touched & present
    isolated = []
    segment = -1
    prior = None
    prior_quarantined = False
    for bar in bars:
        quarantined = bar.time in matched
        if (prior is None or quarantined or prior_quarantined or
                bar.segment != prior.segment or bar.time - prior.time != _STEP):
            segment += 1
        isolated.append(replace(bar, segment=segment))
        prior, prior_quarantined = bar, quarantined
    original = research(bars)
    quarantine = research(isolated)
    return {
        "audit": "DECLARED_DUPLICATE_M1_BUCKET_FROZEN_SWEEP_SENSITIVITY",
        "dataset_id": dataset_id,
        "source_declared_archive_sha256": archive_sha256,
        "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED",
        "original_m15_count": len(bars),
        "retained_m15_count": len(isolated),
        "declared_duplicate_m1_count": len(duplicates),
        "declared_distinct_touched_m15_buckets": len(touched),
        "quarantined_complete_m15_buckets": len(matched),
        "declared_buckets_not_in_complete_m15_population": len(touched - present),
        "original": _summary(original),
        "quarantined_sensitivity": _summary(quarantine),
        "cohort_split_index_preserved": True,
        "matched_trade_population_preserved": False,
        "duplicate_source_rows_authenticated": False,
        "independent_holdout_verified": False,
        "executable_bid_ask_costs_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
    }


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Nonfinite JSON constant")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("declared_input", type=Path)
    args = parser.parse_args(argv)
    path = args.declared_input.resolve(strict=True)
    if not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("Missing or oversized declared input")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream, object_pairs_hook=_strict_object,
                            parse_constant=_invalid_constant)
    if type(payload) is not dict or set(payload) != {
            "dataset_id", "archive_sha256", "bars", "duplicate_m1_times"}:
        raise ValueError("Closed-schema declared input required")
    raw_bars = payload["bars"]
    if type(raw_bars) is not list or not 1 <= len(raw_bars) <= _MAX_BARS:
        raise ValueError("Bounded M15 bars required")
    bars = []
    for row in raw_bars:
        if type(row) is not dict or set(row) != {"time", "o", "h", "l", "c", "segment"}:
            raise ValueError("Closed-schema M15 row required")
        if type(row["segment"]) is not int:
            raise ValueError("Invalid segment")
        prices = []
        for key in ("o", "h", "l", "c"):
            value = row[key]
            if type(value) is not str or len(value) > 64:
                raise ValueError("Expected bounded Decimal price string")
            try:
                prices.append(Decimal(value))
            except Exception as exc:
                raise ValueError("Invalid Decimal price string") from exc
        bars.append(Bar(_parse_clock(row["time"], quarter=True), *prices,
                        row["segment"]))
    result = audit_declared_duplicate_minutes(
        bars, payload["duplicate_m1_times"], dataset_id=payload["dataset_id"],
        archive_sha256=payload["archive_sha256"])
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
