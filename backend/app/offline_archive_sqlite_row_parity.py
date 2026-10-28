"""Fail-closed, read-only original ASCII ZIP -> SQLite accepted-row parity census.

Replays the *declared* HistData importer monotonic-timestamp rule without writes.
Original Decimal text and stored SQLite FLOAT are not interchangeable. Matching
FLOAT values under a declared offset is not vendor-clock or licensing proof.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import timedelta, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import sqlite3
import zipfile

from .archive_duplicate_parity import _records
from .offline_sweep_sqlite_replay import _compressed_archive_digest

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ROWS = 5_000_000
_MAX_UNCOMPRESSED = 512 * 1024 * 1024


def audit_original_ascii_sqlite(archive_zip, sqlite_path, dataset_id, expected_sha256):
    """Compare every admitted original row with the same SQLite source line.

    An exact ZIP SHA and a coherent SQLite read snapshot are required. Duplicate
    or backward source rows are counted as rejected, not silently repaired.
    Only one ASCII CSV member (plus optional status TXT) is supported.
    """
    if any(not isinstance(x, str) or not _SHA.fullmatch(x)
           for x in (dataset_id, expected_sha256)):
        raise ValueError("Explicit lowercase dataset and archive SHA-256 required")
    archive = Path(archive_zip).resolve(strict=True)
    db = Path(sqlite_path).resolve(strict=True)
    if not db.is_file():
        raise ValueError("Expected SQLite file")
    digest_before = _compressed_archive_digest(archive)
    if digest_before[0] != expected_sha256:
        raise ValueError("Original ZIP SHA-256 mismatch")
    with zipfile.ZipFile(archive) as zf:
        csv_members = [m.filename for m in zf.infolist()
                       if m.filename.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise ValueError("Exactly one source CSV required")
        member_name = csv_members[0]

    counts = dict(rows=0, adjacent_duplicate_minutes=0,
                  conflicting_adjacent_duplicate_ohlc=0, backward_jumps=0,
                  zero_volume_rows=0, vendor_status_report_present=False)
    source_rows = _records(archive, "ascii", counts, max_rows=_MAX_ROWS,
                           max_uncompressed_bytes=_MAX_UNCOMPRESSED)
    accepted = rejected = float_precision_loss = 0
    last_accepted = None
    last_epoch = None
    # A read-only connection and explicit transaction pin metadata and rows
    # together even when a separate WAL writer commits concurrently.
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=3)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        metadata = conn.execute(
            "SELECT provider,format,state,utc_offset_minutes,archive_sha256,"
            "accepted,rejected FROM historical_datasets WHERE id=?", (dataset_id,)
        ).fetchone()
        if metadata is None:
            raise ValueError("Dataset not found")
        provider, fmt, state, offset, declared_sha, stored_accepted, stored_rejected = metadata
        if (provider != "HistData" or fmt != "ascii" or state != "READY" or
                type(offset) is not int or not -840 <= offset <= 840 or
                type(stored_accepted) is not int or type(stored_rejected) is not int or
                not 0 < stored_accepted <= _MAX_ROWS or stored_rejected < 0 or
                declared_sha != expected_sha256):
            raise ValueError("Dataset metadata or source identity invalid")
        cursor = iter(conn.execute(
            "SELECT time,open,high,low,close,source_member,source_line "
            "FROM historical_candles WHERE dataset_id=? ORDER BY source_line",
            (dataset_id,)))
        try:
            for line_number, (wall_time, prices) in enumerate(source_rows, 1):
                epoch = int(wall_time.replace(
                    tzinfo=timezone(timedelta(minutes=offset))).timestamp())
                if epoch % 60:
                    raise ValueError("Non-minute UTC conversion")
                if last_epoch is not None and epoch <= last_epoch:
                    rejected += 1
                    continue
                last_epoch = epoch
                accepted += 1
                stored = next(cursor, None)
                if stored is None:
                    raise ValueError("Source accepted row missing in SQLite")
                stamp, o, h, l, c, member, source_line = stored
                if (type(stamp) is not int or stamp != epoch or
                        type(source_line) is not int or source_line != line_number or
                        member != member_name):
                    raise ValueError("Source timestamp or lineage mismatch")
                for original, db_float in zip(prices, (o, h, l, c)):
                    if (original <= 0 or type(db_float) is not float or
                            not math.isfinite(db_float) or db_float <= 0 or
                            not math.isfinite(float(original)) or
                            float(original) != db_float):
                        raise ValueError("Source/SQLite OHLC FLOAT parity mismatch")
                    if original != Decimal(str(db_float)):
                        float_precision_loss += 1
                last_accepted = line_number
        finally:
            source_rows.close()
        if next(cursor, None) is not None:
            raise ValueError("SQLite contains unmatched accepted rows")
        if accepted != stored_accepted or rejected != stored_rejected:
            raise ValueError("Source accepted/rejected census disagrees with SQLite")
        if counts["rows"] != accepted + rejected:
            raise ValueError("Source census does not reconcile")
    if _compressed_archive_digest(archive) != digest_before:
        raise ValueError("Original ZIP changed during parity census")
    return {
        "audit": "ORIGINAL_ASCII_TO_SQLITE_FLOAT_ROW_PARITY",
        "status": "DECLARED_OFFSET_FLOAT_ROW_PARITY_ONLY",
        "dataset_id": dataset_id,
        "archive_sha256": digest_before[0],
        "original_zip_bytes": digest_before[1],
        "source_rows": counts["rows"],
        "source_admitted": accepted,
        "source_quarantined_nonmonotonic": rejected,
        "source_backward_jumps": counts["backward_jumps"],
        "source_adjacent_duplicate_minutes": counts["adjacent_duplicate_minutes"],
        "original_decimal_values_not_preserved_by_float": float_precision_loss,
        "declared_utc_offset_minutes": offset,
        "last_admitted_source_line": last_accepted,
        "zip_identity_verified": True,
        "source_clock_verified": False,
        "source_authenticity_verified": False,
        "usage_rights_verified": False,
        "exact_original_decimal_storage_verified": float_precision_loss == 0,
        "independent_holdout_verified": False,
        "executable_bid_ask_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_zip", type=Path)
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    args = parser.parse_args(argv)
    result = audit_original_ascii_sqlite(
        args.archive_zip, args.sqlite_path, args.dataset_id,
        args.expected_archive_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
