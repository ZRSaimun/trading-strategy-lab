"""Offline cross-archive *claim* analysis for untrusted HistData audit metadata.

This observes possible window overlap and identical reported canonical hashes.
It never opens ZIPs, checks rights, reconciles actual candles or approves import.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json
import re

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INSTRUMENT = re.compile(r"[A-Z0-9]{3,24}\Z")


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid observed timestamp")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid observed timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0) or dt.second or dt.microsecond:
        raise ValueError("Expected minute-aligned UTC timestamp")
    return dt


def summarize_archive_lineage(report: dict, *, sample_limit: int = 20) -> dict:
    """Describe reported metadata only. No assertion of data authenticity.

    The CLI separately invokes the full audit-triage validator first. Calling
    this function directly does not replace that independent prerequisite.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid sample limit")
    if not isinstance(report, dict) or not isinstance(report.get("archives"), list):
        raise ValueError("Invalid inventory")
    entries = report["archives"]
    if not 1 <= len(entries) <= 1000:
        raise ValueError("Invalid inventory size")
    seen = set()
    windows = []
    digests = defaultdict(list)
    missing = 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Invalid archive entry")
        filename, instrument = item.get("file"), item.get("instrument")
        if (not isinstance(filename, str) or not 1 <= len(filename) <= 180
                or not filename.endswith(".zip") or "/" in filename or "\\" in filename
                or filename in seen or not isinstance(instrument, str)
                or not _INSTRUMENT.fullmatch(instrument)):
            raise ValueError("Invalid or duplicate archive identity")
        seen.add(filename)
        first, last = _utc(item.get("first_utc")), _utc(item.get("last_utc"))
        if first > last:
            raise ValueError("Reversed observed range")
        digest = item.get("canonical_bid_ohlc_sha256")
        if digest is None:
            missing += 1
        elif not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("Invalid canonical digest claim")
        else:
            digests[digest].append((filename, instrument, first, last))
        windows.append((filename, instrument, first, last))

    # Same instrument and intersecting *endpoint ranges* do not prove that any
    # observed minute is common. Report the possible collision only.
    overlaps = 0
    overlap_samples = []
    for i, (left, instrument, first, last) in enumerate(windows):
        for right, other_instrument, other_first, other_last in windows[i + 1:]:
            if instrument != other_instrument or max(first, other_first) > min(last, other_last):
                continue
            overlaps += 1
            if len(overlap_samples) < sample_limit:
                overlap_samples.append({
                    "archive_a": left, "archive_b": right,
                    "instrument": instrument,
                    "range_overlap_only": True,
                    "shared_observed_minute_verified": False,
                })

    same_hash_pairs = 0
    same_hash_samples = []
    hash_scope_conflicts = 0
    for group in digests.values():
        for i, (left, instrument, first, last) in enumerate(group):
            for right, other_instrument, other_first, other_last in group[i + 1:]:
                same_hash_pairs += 1
                inconsistent = instrument != other_instrument or first != other_first or last != other_last
                hash_scope_conflicts += int(inconsistent)
                if len(same_hash_samples) < sample_limit:
                    same_hash_samples.append({
                        "archive_a": left, "archive_b": right,
                        "claimed_canonical_bid_ohlc_match": True,
                        "reported_instrument_or_range_conflict": inconsistent,
                        "independent_source_confirmation": False,
                    })

    return {
        "result": "UNTRUSTED_ARCHIVE_LINEAGE_OBSERVATIONS",
        "summary": {
            "archives": len(entries),
            "canonical_digest_reported": len(entries) - missing,
            "canonical_digest_missing": missing,
            "claimed_same_digest_pairs": same_hash_pairs,
            "claimed_digest_scope_conflicts": hash_scope_conflicts,
            "same_instrument_endpoint_range_overlap_pairs": overlaps,
        },
        "claimed_same_digest_samples": same_hash_samples,
        "possible_range_overlap_samples": overlap_samples,
        "sample_limit": sample_limit,
        "raw_zip_bytes_verified": False,
        "independent_source_authenticity_verified": False,
        "source_usage_rights_verified": False,
        "shared_observed_minutes_verified": False,
        "research_ready": False,
        "can_auto_import": False,
        "live": False,
        "may_execute_order": False,
        "limitations": (
            "Input is an untrusted audit summary. Matching reported canonical digests "
            "do not prove independent source confirmation. Overlapping endpoint "
            "ranges do not establish matching candles, market-open minutes, "
            "licensed usage or backtest readiness."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only archive lineage claim audit")
    parser.add_argument("audit", help="Untrusted offline ZIP audit JSON")
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        # Reuse the stricter existing triage before inspecting cross-archive
        # claims; neither stage opens original ZIP files or contacts vendors.
        from .histdata_audit_triage import (
            _read_regular_bounded, _reject_constant, _strict_pairs,
            triage_histdata_audit,
        )
        report = json.loads(_read_regular_bounded(args.audit, 5_000_000),
                            object_pairs_hook=_strict_pairs,
                            parse_constant=_reject_constant)
        triage_histdata_audit(report)
        result = summarize_archive_lineage(report, sample_limit=args.sample_limit)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError):
        print(json.dumps({"result": "REJECTED", "research_ready": False,
                          "can_auto_import": False, "live": False,
                          "may_execute_order": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
