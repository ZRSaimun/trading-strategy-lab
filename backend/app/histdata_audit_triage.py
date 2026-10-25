"""Offline, read-only triage of an *untrusted* historical ZIP audit summary.

This is a consistency and quarantine report, never source authentication,
market-calendar verification, licensing approval, or permission to backtest.
The original ZIP archives must still be checked independently.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import stat


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("Nonstandard JSON constant")


def _read_regular_bounded(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Input is not a bounded regular file")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Input exceeds size limit")
        return raw


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FILE = re.compile(r"[A-Za-z0-9_.()\-]+\.zip\Z")
_COUNTS = ("rows", "unique_timestamps", "duplicate_timestamps",
           "conflicting_duplicate_ohlc", "backward_timestamp_jumps",
           "invalid_rows", "outside_filename_period_rows", "zero_volume_rows",
           "observed_gap_events", "unobserved_minutes_between_rows",
           "largest_gap_minutes")
_FALSE_FLAGS = ("source_authenticity_verified", "reuse_rights_verified",
                "live", "executable_bid_ask_verified", "can_trade")


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"Invalid {name}")
    return value


def _utc_timestamp(value, name):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError(f"Invalid {name}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"Non-UTC {name}")
    return parsed.astimezone(timezone.utc)


def triage_histdata_audit(report: dict) -> dict:
    """Check scanner report arithmetic and conservatively classify archives.

    All entries remain blocked for research, even if their format has no detected
    collisions: this report does not contain independently verified source rights.
    """
    if not isinstance(report, dict) or not isinstance(report.get("summary"), dict):
        raise ValueError("Expected audit and summary objects")
    archives = report.get("archives")
    if not isinstance(archives, list) or not 1 <= len(archives) <= 1000:
        raise ValueError("Invalid archive inventory")
    names, hashes = set(), set()
    output = []
    totals = dict.fromkeys(("rows", "duplicate_timestamps",
                            "conflicting_duplicate_ohlc", "backward_timestamp_jumps"), 0)
    format_ok = quarantine = 0
    for item in archives:
        if not isinstance(item, dict):
            raise ValueError("Invalid archive record")
        filename, digest = item.get("file"), item.get("archive_sha256")
        if (not isinstance(filename, str) or not _FILE.fullmatch(filename)
                or filename in names or not isinstance(digest, str)
                or not _SHA256.fullmatch(digest) or digest in hashes):
            raise ValueError("Ambiguous archive identity")
        names.add(filename)
        hashes.add(digest)
        for flag in _FALSE_FLAGS:
            if item.get(flag) is not False:
                raise ValueError("Source and execution claims must remain unverified")
        if item.get("price_side") != "bid" or item.get("format") not in ("ASCII", "MT"):
            raise ValueError("Unsupported declared price-side or format")
        if not isinstance(item.get("instrument"), str) or not re.fullmatch(r"[A-Z0-9]{3,24}", item["instrument"]):
            raise ValueError("Missing exact instrument label")
        if not isinstance(item.get("archive_bytes"), int) or type(item["archive_bytes"]) is not int or item["archive_bytes"] <= 0:
            raise ValueError("Invalid archive byte count")
        counts = {name: _integer(item.get(name), name, minimum=1 if name == "rows" else 0)
                  for name in _COUNTS}
        if (counts["unique_timestamps"] + counts["duplicate_timestamps"] != counts["rows"]
                or counts["conflicting_duplicate_ohlc"] > counts["duplicate_timestamps"]
                or any(counts[k] > counts["rows"] for k in (
                    "unique_timestamps", "duplicate_timestamps", "backward_timestamp_jumps",
                    "invalid_rows", "outside_filename_period_rows", "zero_volume_rows",
                    "observed_gap_events"))):
            raise ValueError("Inconsistent archive row counters")
        offset = _integer(item.get("fixed_utc_offset_minutes"), "offset", minimum=-840)
        if offset > 840:
            raise ValueError("Invalid fixed offset")
        first, last = (_utc_timestamp(item.get(key), key) for key in ("first_utc", "last_utc"))
        if first > last:
            raise ValueError("Reversed observed UTC range")
        # The source scanner's gap count is defined over the sorted set of
        # observed, minute-aligned timestamps, not market-open expectations.
        # Its arithmetic must reconcile with the declared endpoint range.
        if any(t.second or t.microsecond for t in (first, last)):
            raise ValueError("Observed UTC endpoints must be minute-aligned")
        span_minutes = int((last - first).total_seconds() // 60)
        unique = counts["unique_timestamps"]
        missing = counts["unobserved_minutes_between_rows"]
        events = counts["observed_gap_events"]
        largest = counts["largest_gap_minutes"]
        if unique < 1 or unique > span_minutes + 1 or missing != span_minutes + 1 - unique:
            raise ValueError("Observed timestamp span and gap counts disagree")
        if events > unique - 1 or events > missing:
            raise ValueError("Impossible observed gap event count")
        if (events == 0 and (missing or largest)) or (
            events > 0 and not (2 <= largest <= missing + 1)
        ):
            raise ValueError("Impossible largest observed gap")
        for prefix, instant in (("first", first), ("last", last)):
            local = item.get(f"{prefix}_local_EST")
            if not isinstance(local, str) or len(local) > 32:
                raise ValueError("Missing source wall clock")
            try:
                wall = datetime.fromisoformat(local)
            except ValueError as exc:
                raise ValueError("Malformed source wall clock") from exc
            if wall.tzinfo is not None or wall.replace(tzinfo=timezone(timedelta(minutes=offset))).astimezone(timezone.utc) != instant:
                raise ValueError("Source wall clock and declared fixed offset disagree")
        reasons = []
        if counts["duplicate_timestamps"]:
            reasons.append("DUPLICATE_TIMESTAMPS")
        if counts["conflicting_duplicate_ohlc"]:
            reasons.append("CONFLICTING_DUPLICATE_PRICES")
        if counts["backward_timestamp_jumps"]:
            reasons.append("BACKWARD_TIMESTAMP_JUMPS")
        if counts["invalid_rows"]:
            reasons.append("INVALID_ROWS")
        if counts["outside_filename_period_rows"]:
            reasons.append("OUTSIDE_FILENAME_PERIOD")
        status = "QUARANTINE_REVIEW" if reasons else "FORMAT_OK_NO_COLLISIONS"
        if item.get("status") != status:
            raise ValueError("Scanner status contradicts counters")
        if reasons:
            quarantine += 1
        else:
            format_ok += 1
        for key in totals:
            totals[key] += counts[key]
        output.append({
            "archive": filename,
            "instrument": item["instrument"],
            "declared_format": item["format"],
            "triage": status if reasons else "FORMAT_ONLY_RIGHTS_UNVERIFIED",
            "reasons": reasons if reasons else ["PROVENANCE_AND_RIGHTS_UNVERIFIED"],
            "observed_rows": counts["rows"],
            "conflicting_duplicate_minutes": counts["conflicting_duplicate_ohlc"],
            "volume_dependent_research_allowed": False,
            "research_ready": False,
            "can_auto_import": False,
        })
    expected = {"archives": len(archives), "format_ok_no_collisions": format_ok,
                "quarantine_review": quarantine, **totals}
    if any(_integer(report["summary"].get(k), k) != v for k, v in expected.items()):
        raise ValueError("Summary does not reconcile to archive records")
    return {
        "result": "OFFLINE_UNVERIFIED_AUDIT_TRIAGE",
        "summary": expected,
        "archives": output,
        "research_ready": False,
        "can_auto_import": False,
        "source_authenticity_verified": False,
        "reuse_rights_verified": False,
        "market_calendar_verified": False,
        "live": False,
        "may_execute_order": False,
        "limitations": "Scanner metadata is not source evidence; revalidate original ZIPs, clock conventions and usage rights before any research import.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline HistData audit triage; never imports data")
    parser.add_argument("audit", help="Read-only JSON audit report")
    args = parser.parse_args(argv)
    try:
        raw = _read_regular_bounded(args.audit, 5_000_000)
        report = json.loads(raw, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
        result = triage_histdata_audit(report)
    except (ValueError, OSError, TypeError, KeyError, OverflowError):
        print(json.dumps({"result": "REJECTED", "research_ready": False,
                          "can_auto_import": False, "live": False, "may_execute_order": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
