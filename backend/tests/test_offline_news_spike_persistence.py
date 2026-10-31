"""Synthetic tests only: no authenticated market events or execution claims."""
from datetime import datetime, timedelta, timezone
import pytest
from app.offline_news_spike_persistence import census_news_spike_persistence

T = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


def stamp(i):
    return (T + timedelta(minutes=i)).isoformat()


def candles(*, spike="up", missing=(), end=60):
    result = []
    for i in range(-15, end):
        if i in missing:
            continue
        hi, lo, close = ("101", "99", "100")
        if i == 0:
            if spike == "up":
                hi, close = "103", "102"
            elif spike == "down":
                lo, close = "97", "98"
            elif spike == "both":
                hi, lo = "103", "97"
        result.append({"time": stamp(i), "open": "100", "high": hi,
                       "low": lo, "close": close})
    return result


def run(rows, **kwargs):
    return census_news_spike_persistence(rows, [{"event_id": "synthetic", "time": stamp(0)}],
                                         as_of_utc=stamp(61), source_id="synthetic-bid", **kwargs)


def test_up_spike_rejected_by_five_minutes():
    e = run(candles())["events"][0]
    assert e["spike"] == "up"
    assert e["horizons"]["5"] == {"status": "observed", "position": "inside_pre_range", "aligned": False}
    assert e["horizons"]["60"]["aligned"] is False


def test_down_spike():
    e = run(candles(spike="down"))["events"][0]
    assert e["spike"] == "down" and e["horizons"]["15"]["aligned"] is False


def test_two_sided_spike_not_given_direction():
    e = run(candles(spike="both"))["events"][0]
    assert e["spike"] == "both" and e["horizons"]["60"]["aligned"] is None


def test_no_break_and_strict_equality():
    e = run(candles(spike="none"))["events"][0]
    assert e["spike"] == "none" and e["horizons"]["5"]["aligned"] is None


def test_missing_pre_event_quarantines():
    assert run(candles(missing=(-4,)))["events"][0]["status"] == "missing_pre_event_minutes"


def test_missing_first_five_quarantines():
    assert run(candles(missing=(2,)))["events"][0]["status"] == "missing_first_five_minutes"


def test_missing_intermediate_minute_invalidates_later_horizons():
    h = run(candles(missing=(17,)))["events"][0]["horizons"]
    assert h["15"]["status"] == "observed"
    assert h["30"]["status"] == "insufficient_complete_minutes"
    assert h["60"]["status"] == "insufficient_complete_minutes"


def test_lookahead_rejected():
    with pytest.raises(ValueError, match="Uncompleted"):
        census_news_spike_persistence(candles(), [{"event_id": "a", "time": stamp(0)}],
                                      as_of_utc=stamp(10), source_id="source")


def test_unsorted_or_duplicate_rejected():
    rows = candles()
    with pytest.raises(ValueError, match="Unsorted"):
        run(rows + [rows[-1]])


def test_non_utc_rejected():
    rows = candles()
    rows[0]["time"] = "2026-10-28T17:45:00+01:00"
    with pytest.raises(ValueError, match="UTC"):
        run(rows)


def test_nonfinite_rejected():
    rows = candles()
    rows[0]["high"] = "NaN"
    with pytest.raises(ValueError, match="finite"):
        run(rows)


def test_invalid_ohlc_rejected():
    rows = candles()
    rows[0]["low"] = "105"
    with pytest.raises(ValueError, match="Inconsistent"):
        run(rows)


def test_event_overlap_rejected():
    with pytest.raises(ValueError, match="75 minutes"):
        census_news_spike_persistence(candles(),
            [{"event_id": "a", "time": stamp(0)}, {"event_id": "b", "time": stamp(20)}],
            as_of_utc=stamp(61), source_id="source")


def test_no_mutation():
    rows = candles()
    original = [dict(x) for x in rows]
    run(rows)
    assert rows == original


def test_as_of_requires_complete_minute():
    with pytest.raises(ValueError, match="minute-aligned"):
        census_news_spike_persistence([], [], as_of_utc="2026-10-28T18:00:01Z", source_id="source")


def test_empty_events_allowed():
    assert census_news_spike_persistence([], [], as_of_utc=stamp(0), source_id="source")["events"] == []
