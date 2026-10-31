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
        "causal_confirmation_window_coverage": _causal_confirmation_window_coverage(bars, matched),
        "full_horizon_window_coverage": _full_horizon_window_coverage(bars, matched),
        "cohort_split_index_preserved": True,
        "matched_trade_population_preserved": False,
        "duplicate_source_rows_authenticated": False,
        "independent_holdout_verified": False,
        "executable_bid_ask_costs_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
    }



def _causal_confirmation_window_coverage(bars, matched):
    """Causal structural denominator through the *completed confirmation* only.

    Same frozen candidate sweep indices, 70/30 split and embargo as research().
    Does not inspect entry/exit bars, prices or signals; never use as a filter.
    """
    n = len(bars)
    split = n * 7 // 10
    broken_prefix = [0] * (n + 1)
    touched_prefix = [0] * (n + 1)
    for j, bar in enumerate(bars):
        broken = (j > 0 and (
            bar.segment != bars[j - 1].segment or
            bar.time - bars[j - 1].time != _STEP))
        broken_prefix[j + 1] = broken_prefix[j] + int(broken)
        touched_prefix[j + 1] = touched_prefix[j] + int(bar.time in matched)
    counts = {
        name: {
            "possible_sweep_indices": 0,
            "confirmation_crosses_source_gap_or_segment": 0,
            "original_contiguous_confirmation_windows": 0,
            "declared_duplicate_touched_confirmation_windows": 0,
            "quarantine_clean_confirmation_windows": 0,
        } for name in ("development", "exploratory_later")
    }
    # Mutually exclusive *causal* contamination phase combinations. The
    # sweep and completed confirmation are distinct from the prior 16 bars.
    # This is a structural denominator, never a signal-selection feature.
    phase_names = {
        1: "PRIOR_ONLY",
        2: "SWEEP_ONLY",
        3: "PRIOR_AND_SWEEP",
        4: "CONFIRMATION_ONLY",
        5: "PRIOR_AND_CONFIRMATION",
        6: "SWEEP_AND_CONFIRMATION",
        7: "PRIOR_SWEEP_AND_CONFIRMATION",
    }
    phase_counts = {
        name: {label: 0 for label in phase_names.values()} for name in counts
    }
    for i in range(16, n - 1):
        cohort = ("development" if i + 1 < split - 16 else
                  "exploratory_later" if i >= split + 16 else None)
        if cohort is None:
            continue
        cell = counts[cohort]
        cell["possible_sweep_indices"] += 1
        start, end = i - 16, i + 1  # 16 completed prior + sweep + confirmation
        if broken_prefix[end + 1] - broken_prefix[start + 1]:
            cell["confirmation_crosses_source_gap_or_segment"] += 1
            continue
        cell["original_contiguous_confirmation_windows"] += 1
        if touched_prefix[end + 1] - touched_prefix[start]:
            cell["declared_duplicate_touched_confirmation_windows"] += 1
            phase_mask = (
                int(touched_prefix[i] > touched_prefix[i - 16]) |
                (2 if bars[i].time in matched else 0) |
                (4 if bars[i + 1].time in matched else 0)
            )
            if phase_mask == 0:
                raise RuntimeError("Causal contamination phase census mismatch")
            phase_counts[cohort][phase_names[phase_mask]] += 1
        else:
            cell["quarantine_clean_confirmation_windows"] += 1
    for name, cell in counts.items():
        if sum(phase_counts[name].values()) != cell[
                "declared_duplicate_touched_confirmation_windows"]:
            raise RuntimeError("Causal phase attribution reconciliation failed")
        if (cell["possible_sweep_indices"] !=
                cell["confirmation_crosses_source_gap_or_segment"] +
                cell["original_contiguous_confirmation_windows"] or
                cell["original_contiguous_confirmation_windows"] !=
                cell["declared_duplicate_touched_confirmation_windows"] +
                cell["quarantine_clean_confirmation_windows"]):
            raise RuntimeError("Causal confirmation window reconciliation failed")
    return {
        "scope": "COMPLETED_CONFIRMATION_CAUSAL_STRUCTURE_NOT_SIGNAL_SELECTION",
        "frozen_prior_m15_bars": 16,
        "frozen_split_fraction": "70/30_BY_BAR_INDEX",
        "frozen_embargo_m15_bars": 16,
        "future_entry_or_exit_bars_inspected": False,
        "does_not_measure_trade_or_signal_count": True,
        "does_not_prove_executable_or_profitable_outcomes": True,
        "cohorts": counts,
        "contamination_phase_attribution": {
            "scope": "COMPLETED_CONFIRMATION_PHASES_ONLY_NOT_SIGNAL_SELECTION",
            "mutually_exclusive": True,
            "future_entry_or_exit_bars_inspected": False,
            "cohorts": phase_counts,
        },
    }

def _full_horizon_window_coverage(bars, matched):
    """Post-outcome observability envelope, NEVER a pre-entry signal filter.

    For each index that *could* be a sweep under the frozen split/embargo,
    count whether 16 prior bars + sweep + confirmation + 16 entry/horizon
    bars are fully contiguous and whether any declared duplicate-touched
    bucket intersects that entire window. No price, signal or exit is read.
    """
    n = len(bars)
    split = n * 7 // 10
    broken_prefix = [0] * (n + 1)
    touched_prefix = [0] * (n + 1)
    for j, bar in enumerate(bars):
        broken = (j > 0 and (
            bar.segment != bars[j - 1].segment or
            bar.time - bars[j - 1].time != _STEP))
        broken_prefix[j + 1] = broken_prefix[j] + int(broken)
        touched_prefix[j + 1] = touched_prefix[j] + int(bar.time in matched)
    counts = {
        name: {
            "possible_sweep_indices": 0,
            "full_horizon_outside_cohort_or_archive": 0,
            "full_horizon_crosses_source_gap_or_segment": 0,
            "original_contiguous_full_horizon_windows": 0,
            "declared_duplicate_touched_full_horizon_windows": 0,
            "quarantine_clean_full_horizon_windows": 0,
        } for name in ("development", "exploratory_later")
    }
    for i in range(16, n - 1):
        cohort = ("development" if i + 1 < split - 16 else
                  "exploratory_later" if i >= split + 16 else None)
        if cohort is None:
            continue
        cell = counts[cohort]
        cell["possible_sweep_indices"] += 1
        start, end = i - 16, i + 17  # 16 prior + sweep + confirm + 16 horizon
        if end >= n or (cohort == "development" and end >= split - 16):
            cell["full_horizon_outside_cohort_or_archive"] += 1
            continue
        if broken_prefix[end + 1] - broken_prefix[start + 1]:
            cell["full_horizon_crosses_source_gap_or_segment"] += 1
            continue
        cell["original_contiguous_full_horizon_windows"] += 1
        if touched_prefix[end + 1] - touched_prefix[start]:
            cell["declared_duplicate_touched_full_horizon_windows"] += 1
        else:
            cell["quarantine_clean_full_horizon_windows"] += 1
    for cell in counts.values():
        if (cell["possible_sweep_indices"] !=
                cell["full_horizon_outside_cohort_or_archive"] +
                cell["full_horizon_crosses_source_gap_or_segment"] +
                cell["original_contiguous_full_horizon_windows"] or
                cell["original_contiguous_full_horizon_windows"] !=
                cell["declared_duplicate_touched_full_horizon_windows"] +
                cell["quarantine_clean_full_horizon_windows"]):
            raise RuntimeError("Full-horizon window population reconciliation failed")
    return {
        "scope": "POST_OUTCOME_OBSERVABILITY_ENVELOPE_NOT_SIGNAL_SELECTION",
        "frozen_prior_m15_bars": 16,
        "frozen_horizon_m15_bars": 16,
        "frozen_split_fraction": "70/30_BY_BAR_INDEX",
        "frozen_embargo_m15_bars": 16,
        "does_not_measure_trade_or_signal_count": True,
        "does_not_prove_executable_or_profitable_outcomes": True,
        "cohorts": counts,
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
