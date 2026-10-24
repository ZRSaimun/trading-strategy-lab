"""Regression tests for bounded-memory historical candle aggregation."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.history import latest_aggregates
from app.market import bucket


def rows(times, volume=1):
    return [SimpleNamespace(time=t, open=float(i), high=float(i + 2),
                            low=float(i - 1), close=float(i + 1), volume=volume)
            for i, t in enumerate(times)]


def test_five_minute_buckets_keep_open_close_and_volume():
    ascending = rows([0, 60, 120, 180, 240, 300, 360, 420])
    result, more = latest_aggregates(reversed(ascending), "5m")
    assert not more
    assert result == [
        {"time": 0, "open": 0.0, "high": 6.0, "low": -1.0,
         "close": 5.0, "volume": 5, "observed_minutes": 5},
        {"time": 300, "open": 5.0, "high": 9.0, "low": 4.0,
         "close": 8.0, "volume": 3, "observed_minutes": 3},
    ]


def test_pages_stop_after_extra_completed_bucket():
    ascending = rows([60*i for i in range(100000)])
    consumed = 0
    def stream():
        nonlocal consumed
        for item in reversed(ascending):
            consumed += 1
            yield item
    result, more = latest_aggregates(stream(), "1m", limit=3)
    assert more
    assert [r["time"] for r in result] == [60*99997, 60*99998, 60*99999]
    assert consumed <= 5


def test_before_boundary_requires_no_partial_bucket():
    ascending = rows([0, 60, 120, 180, 240, 300, 360, 420])
    result, more = latest_aggregates((r for r in reversed(ascending) if r.time < 300), "5m")
    assert not more
    assert len(result) == 1
    assert result[0]["observed_minutes"] == 5


def test_empty_gaps_unknown_volume_and_paging():
    assert latest_aggregates(iter([]), "1m") == ([], False)
    original = rows([0, 600, 1200], volume=None)
    result, more = latest_aggregates(reversed(original), "5m", limit=2)
    assert more
    assert [r["time"] for r in result] == [600, 1200]
    assert all(r["volume"] is None for r in result)


def test_month_week_and_invalid_timeframe():
    t = lambda date: int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())
    original = rows([t("2026-09-30"), t("2026-10-01"), t("2026-10-20")])
    result, more = latest_aggregates(reversed(original), "1M")
    assert [r["time"] for r in result] == [t("2026-09-01"), t("2026-10-01")]
    assert result[1]["observed_minutes"] == 2
    result, _ = latest_aggregates(reversed(original), "1W")
    assert len(result) == 2
    with pytest.raises(ValueError):
        latest_aggregates(iter([]), "17m")
    with pytest.raises(ValueError):
        latest_aggregates(iter([]), "1m", limit=0)


def test_streaming_matches_reference_aggregation_for_many_intervals():
    ascending = rows([60*i for i in range(12000) if i % 67 != 0], volume=0.5)
    for tf in ("1m", "3m", "5m", "15m", "1H", "4H", "1D", "1W", "1M"):
        groups = {}
        for r in ascending:
            key = bucket(r.time, tf)
            if key not in groups:
                groups[key] = dict(time=key, open=r.open, high=r.high, low=r.low,
                                   close=r.close, volume=r.volume, observed_minutes=1)
            else:
                bar = groups[key]
                bar["high"] = max(bar["high"], r.high)
                bar["low"] = min(bar["low"], r.low)
                bar["close"] = r.close
                bar["volume"] += r.volume
                bar["observed_minutes"] += 1
        expected = list(groups.values())[-2000:]
        actual, more = latest_aggregates(reversed(ascending), tf)
        assert actual == expected, tf
        assert more == (len(groups) > 2000)
