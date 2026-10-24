"""Bounded-memory pagination for historical OHLCV data.

Input is a database stream sorted newest first. This preserves full timeframe
buckets without materializing all raw candles in application memory. It does
not synthesise missing minutes or assume continuous trading sessions.
"""
from collections.abc import Iterable
from typing import Any

from .market import TIMEFRAMES, bucket


def latest_aggregates(rows_desc: Iterable[Any], timeframe: str, limit: int = 2000) -> tuple[list[dict], bool]:
    """Return at most ``limit`` ascending bars and whether an older bar exists.

    ``rows_desc`` must be descending by candle time and restricted to one
    instrument/dataset. Caller is responsible for database ordering. A ``before``
    filter, if requested, must be applied to raw records before streaming.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported timeframe")
    if limit < 1:
        raise ValueError("limit must be positive")

    bars_desc: list[dict] = []
    current: dict | None = None
    for candle in rows_desc:
        candle_bucket = bucket(candle.time, timeframe)
        if current is not None and candle_bucket != current["time"]:
            bars_desc.append(current)
            # The extra completed bar proves there is an older page. Stop
            # before reading the entire remaining history.
            if len(bars_desc) > limit:
                return list(reversed(bars_desc[:limit])), True
            current = None

        if current is None:
            current = {"time": candle_bucket, "open": candle.open, "high": candle.high,
                       "low": candle.low, "close": candle.close,
                       "volume": candle.volume, "observed_minutes": 1}
        else:
            # Moving backwards in time changes the opening price, not close.
            current["open"] = candle.open
            current["high"] = max(current["high"], candle.high)
            current["low"] = min(current["low"], candle.low)
            current["volume"] = (current["volume"] + candle.volume
                                 if current["volume"] is not None and candle.volume is not None
                                 else None)
            current["observed_minutes"] += 1

    if current is not None:
        bars_desc.append(current)
    return list(reversed(bars_desc[:limit])), len(bars_desc) > limit
