"""Offline, read-only replay of a declared research SQLite M1 dataset.

Uses the existing frozen Decimal sweep engine, but SQLite FLOAT prices are NOT
the original source strings. This is a staging reproducibility check, not
archive authentication, broker backtesting, a holdout, or execution authority.
"""
import argparse
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .offline_sweep_probe import Bar, research

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ROWS = 5_000_000


def _price(value, label):
    if type(value) is not float and type(value) is not int:
        raise ValueError(f"{label}: nonnumeric stored OHLC")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label}: invalid stored OHLC")
    return Decimal(str(value))


def replay_declared_sqlite(path, dataset_id, expected_archive_sha256):
    """Run one isolated dataset; never modify DB or infer source authenticity."""
    if not isinstance(dataset_id, str) or not _SHA256.fullmatch(dataset_id):
        raise ValueError("Expected explicit 64-character dataset ID")
    if (not isinstance(expected_archive_sha256, str) or
            not _SHA256.fullmatch(expected_archive_sha256)):
        raise ValueError("Expected explicit lowercase source archive SHA-256")
    db_path = Path(path).resolve(strict=True)
    if not db_path.is_file():
        raise ValueError("Expected existing SQLite file")
    # SQLite read-only URI and query_only provide independent no-write fences.
    # Do not use immutable=1: ignoring a concurrent WAL could hide changes.
    uri = db_path.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=3)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=3000")
        row = conn.execute(
            "SELECT provider,instrument,format,utc_offset_minutes,"
            "archive_sha256,state,accepted,rejected FROM historical_datasets "
            "WHERE id=?", (dataset_id,)).fetchone()
        if row is None:
            raise ValueError("Dataset not present")
        provider, instrument, fmt, offset, sha, state, accepted, rejected = row
        if (provider != "HistData" or fmt != "ascii" or state != "READY" or
                not isinstance(instrument, str) or not instrument or
                type(offset) is not int or type(accepted) is not int or
                not 1 <= accepted <= _MAX_ROWS or
                type(rejected) is not int or rejected < 0):
            raise ValueError("Unsupported or incomplete declared dataset")
        if sha != expected_archive_sha256:
            raise ValueError("Source archive SHA-256 declaration mismatch")
        bars = []
        bucket = []
        bucket_key = None
        prev_time = None
        prev_line = None
        source_member = None
        segment = 0
        seen = 0
        discontinuities = 0
        discarded = 0

        def flush():
            nonlocal discarded
            if not bucket:
                return
            if len(bucket) == 15 and bucket[0][0] % 900 == 0:
                first = bucket[0]
                bars.append(Bar(
                    datetime.fromtimestamp(first[0], tz=timezone.utc).replace(
                        tzinfo=None),
                    first[1], max(x[2] for x in bucket),
                    min(x[3] for x in bucket), bucket[-1][4], segment))
            else:
                discarded += 1

        cursor = conn.execute(
            "SELECT time,open,high,low,close,volume,source_member,source_line "
            "FROM historical_candles WHERE dataset_id=? ORDER BY time",
            (dataset_id,))
        for stamp, o, h, l, c, volume, member, line in cursor:
            seen += 1
            if seen > _MAX_ROWS:
                raise ValueError("M1 row cap exceeded")
            if (type(stamp) is not int or stamp % 60 != 0 or
                    type(line) is not int or line <= 0 or
                    not isinstance(member, str) or not member):
                raise ValueError("Invalid M1 source timestamp or lineage")
            if source_member is None:
                source_member = member
            if member != source_member or (prev_line is not None and line <= prev_line):
                raise ValueError("Unexpected source member or nonmonotonic source line")
            prices = tuple(_price(x, name) for x, name in
                           zip((o, h, l, c), ("open", "high", "low", "close")))
            op, hi, lo, cl = prices
            if hi < max(op, cl) or lo > min(op, cl) or lo > hi:
                raise ValueError("Invalid stored M1 OHLC geometry")
            if (volume is not None and
                    (type(volume) not in (int, float) or
                     not math.isfinite(volume) or volume < 0)):
                raise ValueError("Invalid stored M1 volume")
            if prev_time is not None and stamp - prev_time != 60:
                flush()
                bucket = []
                bucket_key = None
                segment += 1
                discontinuities += 1
            key = stamp // 900
            if bucket_key is not None and key != bucket_key:
                flush()
                bucket = []
            bucket_key = key
            bucket.append((stamp, op, hi, lo, cl))
            prev_time = stamp
            prev_line = line
        flush()
        if seen != accepted:
            raise ValueError("Stored row count disagrees with READY metadata")
    result = research(bars)
    summary = {}
    for name, cohort in result["cohorts"].items():
        summary[name] = {
            "confirmed": cohort["confirmed_signals"],
            "entered": cohort["entered_positions"],
            "observed": cohort["observed_outcomes"],
            "censored": cohort["censored_due_to_gaps_or_boundaries"],
            "missing_entry": cohort["confirmed_signals_without_observable_entry"],
            "invalid_entry_geometry": cohort["invalid_entry_stop_or_target_geometry"],
            "cost_scenarios": [
                {"extra_bps": s["additional_round_trip_bps"],
                 "observed_count": s["count"],
                 "observed_mean_net_r": s["mean_net_r"]}
                for s in cohort["cost_scenarios"]],
        }
    return {
        "audit": "SQLITE_FLOAT_STAGING_FROZEN_DECIMAL_ENGINE_REPLAY",
        "dataset_id": dataset_id,
        "instrument": instrument,
        "source_declared_sha256": sha,
        "utc_offset_minutes_declared_not_authenticated": offset,
        "m1_accepted": seen,
        "m1_rejected_per_declared_metadata": rejected,
        "complete_m15": len(bars),
        "partial_m15_discarded": discarded,
        "m1_discontinuities": discontinuities,
        "price_precision": "SQLITE_FLOAT_VIA_DECIMAL_STR_NOT_ORIGINAL_TEXT",
        "cohorts": summary,
        "source_authenticated": False,
        "independent_holdout_verified": False,
        "broker_execution_costs_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(replay_declared_sqlite(
        args.sqlite_path, args.dataset_id, args.expected_archive_sha256),
        sort_keys=True))


if __name__ == "__main__":
    main()
