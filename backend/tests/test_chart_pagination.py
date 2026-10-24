from types import SimpleNamespace
from app.market import aggregate, bucket
from app.history import latest_aggregates


def aggregate_recent(rows_descending, timeframe, limit=2000):
    return latest_aggregates((SimpleNamespace(**r) for r in rows_descending), timeframe, limit)


def rows():
    return [dict(time=1704067200+i*60, open=i, high=i+2, low=i-1, close=i+1, volume=1) for i in range(101)]


def test_matches_reference_and_stops_early():
    data = rows()
    consumed = []
    def stream():
        for r in reversed(data):
            consumed.append(r)
            yield r
    result, more = aggregate_recent(stream(), '5m', limit=3)
    assert result == aggregate(data, '5m')[-3:]
    assert more
    assert len(consumed) < len(data)


def test_pages_cover_buckets_without_truncation():
    data = rows()
    expected = aggregate(data, '5m')
    collected = []
    while data:
        page, more = aggregate_recent(reversed(data), '5m', limit=3)
        collected = page + collected
        if not more:
            break
        data = [r for r in data if r['time'] < bucket(page[0]['time'], '5m')]
    assert collected == expected


def test_calendar_and_missing_volume():
    data = rows()
    data[2]['volume'] = None
    for tf in ('1m', '1W', '1M'):
        result, more = aggregate_recent(reversed(data), tf)
        assert result == aggregate(data, tf)
        assert not more
