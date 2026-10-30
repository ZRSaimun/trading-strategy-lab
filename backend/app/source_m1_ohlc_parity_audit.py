"""Read-only, exact-decimal source-order M1 OHLC versus stored-row audit.

Caller-provided rows only. No archives, database, network, price corrections,
research approval, live feed or order execution. Fingerprints are *not* source
authentication and do not establish any right to use market data.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from datetime import datetime, timezone

MAX_ROWS = 100_000
MAX_UTC_MINUTE = 253402300740  # 9999-12-31 23:59:00 UTC
_PRICE = re.compile(r"-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,12})?\Z")
_SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def _price(value: object) -> tuple[Decimal, str]:
    if type(value) is not str or _PRICE.fullmatch(value) is None:
        raise ValueError("OHLC values must be bounded plain decimal strings")
    # Decimal construction is exact, not binary float conversion or rounding.
    number = Decimal(value)
    canonical = value.rstrip("0").rstrip(".") if "." in value else value
    if number == 0:
        canonical = "0"
    return number, canonical


def _rows(value: object, label: str, *, stored: bool) -> list[tuple[int, tuple[str, ...]]]:
    if type(value) is not list or not value or len(value) > MAX_ROWS:
        raise ValueError(f"{label} must be a nonempty bounded list")
    parsed = []
    previous = None
    for row in value:
        if type(row) is not tuple or len(row) != 5:
            raise ValueError(f"{label} rows must be (UTC_epoch, open, high, low, close) tuples")
        minute = row[0]
        if type(minute) is not int or not 0 <= minute <= MAX_UTC_MINUTE or minute % 60:
            raise ValueError(f"{label} contains an invalid UTC M1 epoch")
        if stored and previous is not None and minute <= previous:
            raise ValueError("stored rows must be strictly increasing and unique")
        numbers_and_strings = [_price(v) for v in row[1:]]
        o, h, l, c = (p[0] for p in numbers_and_strings)
        if h < max(o, c, l) or l > min(o, c):
            raise ValueError(f"{label} contains inconsistent OHLC bounds")
        parsed.append((minute, tuple(p[1] for p in numbers_and_strings)))
        previous = minute
    return parsed


def _digest(rows: list[tuple[int, tuple[str, ...]]], scope: str) -> str:
    digest = hashlib.sha256((scope + "\n").encode("ascii"))
    for minute, prices in rows:
        digest.update((str(minute) + "," + ",".join(prices) + "\n").encode("ascii"))
    return digest.hexdigest()


def _utc(minute: int) -> str:
    return datetime.fromtimestamp(minute, timezone.utc).isoformat()


def audit_source_m1_ohlc_parity(
    source_order_rows: list[tuple], stored_unique_rows: list[tuple], *,
    source_id: str, sample_limit: int = 5,
) -> dict:
    """Report exact numeric OHLC parity without exposing prices or approving data.

    Duplicate source minutes always require quarantine, including when their
    OHLC values are identical. Stored rows must already be a frozen read-only
    snapshot. Source timestamps and their UTC conversion must be verified
    independently. Signed/negative values are allowed for generic instruments.
    """
    if type(source_id) is not str or _SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("a bounded source identifier is required")
    if type(sample_limit) is not int or not 0 <= sample_limit <= 20:
        raise ValueError("sample_limit must be an integer from 0 to 20")
    source = _rows(source_order_rows, "source_order_rows", stored=False)
    stored = _rows(stored_unique_rows, "stored_unique_rows", stored=True)
    first_seen = {}
    repeated = identical_repeats = conflicting_repeats = backward = 0
    repeat_samples, conflict_samples = [], []
    previous = None
    for ordinal, (minute, ohlc) in enumerate(source, 1):
        if previous is not None and minute < previous:
            backward += 1
        if minute in first_seen:
            repeated += 1
            if len(repeat_samples) < sample_limit:
                repeat_samples.append({"row_ordinal": ordinal, "minute_utc": _utc(minute)})
            if ohlc == first_seen[minute]:
                identical_repeats += 1
            else:
                conflicting_repeats += 1
                if len(conflict_samples) < sample_limit:
                    conflict_samples.append({"row_ordinal": ordinal, "minute_utc": _utc(minute)})
        else:
            first_seen[minute] = ohlc
        previous = minute
    stored_by_minute = dict(stored)
    source_minutes = set(first_seen)
    stored_minutes = set(stored_by_minute)
    missing = sorted(source_minutes - stored_minutes)
    extra = sorted(stored_minutes - source_minutes)
    mismatched = sorted(
        minute for minute in source_minutes & stored_minutes
        if first_seen[minute] != stored_by_minute[minute]
    )
    quarantine = bool(repeated or backward or missing or extra or mismatched)
    return {
        "result": "QUARANTINE_REQUIRED" if quarantine else "EXACT_DECIMAL_PARITY_ONLY_UNVERIFIED",
        "source_id": source_id,
        "source_order_rows_sha256": _digest(source, "SOURCE_ORDER_M1_OHLC_V1"),
        "stored_unique_rows_sha256": _digest(stored, "STORED_UNIQUE_M1_OHLC_V1"),
        "fingerprint_scope": "caller-provided UTC epochs and normalized exact-decimal OHLC; not original ZIP bytes or signed database state",
        "source_rows": len(source),
        "source_distinct_minutes": len(first_seen),
        "stored_distinct_minutes": len(stored),
        "source_repeated_rows": repeated,
        "source_identical_repeated_rows": identical_repeats,
        "source_conflicting_repeated_rows": conflicting_repeats,
        "source_backward_timestamp_jumps": backward,
        "source_repeated_samples": repeat_samples,
        "source_conflicting_repeated_samples": conflict_samples,
        "source_unique_missing_from_store": len(missing),
        "stored_minutes_absent_from_source": len(extra),
        "first_seen_source_ohlc_mismatched_in_store": len(mismatched),
        "source_missing_from_store_samples_utc": [_utc(t) for t in missing[:sample_limit]],
        "stored_absent_from_source_samples_utc": [_utc(t) for t in extra[:sample_limit]],
        "source_store_ohlc_mismatch_samples_utc": [_utc(t) for t in mismatched[:sample_limit]],
        "timestamp_conversion_verified": False,
        "original_archive_authenticated": False,
        "source_licensing_verified": False,
        "independent_market_calendar_verified": False,
        "research_ready": False,
        "live": False,
        "may_execute_order": False,
    }
