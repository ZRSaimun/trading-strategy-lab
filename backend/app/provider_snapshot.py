"""Fail-closed consistency check between normalized candles and stored source snapshot.

This verifies internal byte-to-row consistency, not vendor authenticity, licensing,
exchange timestamp semantics, or executable market prices.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import math


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous JSON at every object depth; last-key-wins is unsafe."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate source snapshot JSON key')
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    """JSON NaN/Infinity are not valid portable source evidence."""
    raise ValueError('Nonstandard source snapshot JSON constant')


def verify_normalized_snapshot(rows: list[dict], archive: bytes, expected_symbol: str) -> None:
    """Reject mismatches before a content-addressed archive or database is written.

    The Twelve Data normalizer emits an exact, narrow JSON structure with
    source-field strings and UTC ISO timestamps. Never reconstruct missing rows.
    """
    if not isinstance(archive, bytes) or not 0 < len(archive) <= 3_000_000:
        raise ValueError('Invalid source snapshot size or type')
    if not isinstance(expected_symbol, str) or not expected_symbol:
        raise ValueError('Expected symbol is required')
    if not isinstance(rows, list) or not rows or len(rows) > 5000:
        raise ValueError('Invalid normalized candle count')
    try:
        snapshot = json.loads(archive, object_pairs_hook=_reject_duplicate_keys,
                              parse_constant=_reject_nonstandard_constant)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Invalid source snapshot JSON') from None
    if not isinstance(snapshot, dict) or set(snapshot) != {'meta', 'values'}:
        raise ValueError('Invalid source snapshot structure')
    if snapshot['meta'] != {
        'symbol': expected_symbol, 'interval': '1min', 'exchange_timezone': 'UTC'
    }:
        raise ValueError('Source snapshot metadata mismatch')
    values = snapshot['values']
    if not isinstance(values, list) or len(values) != len(rows):
        raise ValueError('Source snapshot row count mismatch')
    for source, row in zip(values, rows):
        if not isinstance(source, dict) or set(source) != {'time', 'open', 'high', 'low', 'close'}:
            raise ValueError('Invalid source snapshot candle fields')
        if not isinstance(row, dict) or type(row.get('time')) is not int:
            raise ValueError('Invalid normalized candle timestamp')
        stamp = source['time']
        if not isinstance(stamp, str):
            raise ValueError('Invalid source snapshot timestamp')
        try:
            dt = datetime.fromisoformat(stamp)
            if (dt.tzinfo is None or dt.utcoffset() != timedelta(0)
                    or dt.second or dt.microsecond or int(dt.timestamp()) != row['time']):
                raise ValueError('Source snapshot UTC timestamp mismatch')
            for field in ('open', 'high', 'low', 'close'):
                value = source[field]
                if type(value) not in (str, int, float):
                    raise ValueError('Invalid source snapshot OHLC type')
                numeric = float(value)
                if not math.isfinite(numeric) or numeric != row.get(field):
                    raise ValueError('Source snapshot OHLC mismatch')
            if row.get('volume') is not None:
                raise ValueError('Unexpected volume in volume-free source snapshot')
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Source snapshot candle mismatch') from None
