"""Deterministic synthetic tests; no vendor requests or actual market prices."""
import pytest
from app.completed_candle_quality import assess_completed_m1


def candles(*times):
    return [{'time': t, 'open': 100.0, 'high': 102.0, 'low': 99.0, 'close': 101.0} for t in times]


def test_contiguous_complete_bars_have_no_observed_gaps():
    report = assess_completed_m1(candles(60, 120, 180), 300)
    assert report['observed_candles'] == 3
    assert report['observed_timestamp_gaps'] == 0
    assert report['unobserved_minutes_between_candles'] == 0
    assert report['seconds_since_last_candle_close'] == 60
    assert report['last_candle_close_utc'] == '1970-01-01T00:04:00+00:00'
    assert not report['live'] and not report['may_execute_order']
    assert not report['market_calendar_checked']
    assert report['ohlc_invariants_checked'] and report['price_side'] == 'UNVERIFIED'


def test_gaps_are_observations_not_missing_market_claims():
    report = assess_completed_m1(candles(60, 240, 300, 720), 900)
    assert report['observed_timestamp_gaps'] == 2
    assert report['unobserved_minutes_between_candles'] == 8
    assert report['largest_unobserved_span_minutes'] == 6
    assert [g['unobserved_minutes'] for g in report['gap_samples']] == [2, 6]
    assert 'market closures' in report['caveat']


def test_bounded_samples_preserve_exact_counts():
    report = assess_completed_m1(candles(60, 180, 300, 420), 600, sample_limit=1)
    assert report['observed_timestamp_gaps'] == 3
    assert report['unobserved_minutes_between_candles'] == 3
    assert len(report['gap_samples']) == 1
    assert assess_completed_m1(candles(60, 180), 300, sample_limit=0)['gap_samples'] == []


@pytest.mark.parametrize('rows', [[], candles(60, 60), candles(120, 60),
                                     candles(61), [{'time': 60.0}], [{'time': True}],
                                     [{'time': '60'}], [None], candles(-60)])
def test_bad_timestamp_inputs_fail_closed(rows):
    with pytest.raises(ValueError):
        assess_completed_m1(rows, 300)


def test_incomplete_or_future_bars_fail_closed():
    with pytest.raises(ValueError):
        assess_completed_m1(candles(60, 240), 299)
    with pytest.raises(ValueError):
        assess_completed_m1(candles(300), 300)
    assert assess_completed_m1(candles(240), 300)['seconds_since_last_candle_close'] == 0


@pytest.mark.parametrize('now,limit', [(60.0, 5), (True, 5), (-1, 5), (300, -1), (300, 21), (300, True)])
def test_invalid_clock_or_sample_limit_fails_closed(now, limit):
    with pytest.raises(ValueError):
        assess_completed_m1(candles(60), now, sample_limit=limit)


def test_read_only_and_stale_never_becomes_live():
    rows = candles(60, 120)
    original = [dict(row) for row in rows]
    report = assess_completed_m1(rows, 60 * 60 * 24 * 365)
    assert rows == original
    assert report['seconds_since_last_candle_close'] > 0
    assert not report['live'] and not report['executable_bid_ask_verified']
    assert not report['provider_entitlement_verified']


@pytest.mark.parametrize('bad', [
    {'open': True}, {'open': '100'}, {'high': float('nan')},
    {'close': float('inf')}, {'low': 103.0}, {'high': 98.0},
    {'volume': -1}, {'volume': float('nan')}, {'volume': True},
    {'open': None},
])
def test_malformed_ohlc_or_volume_fails_closed(bad):
    row = {**candles(60)[0], **bad}
    with pytest.raises(ValueError):
        assess_completed_m1([row], 300)


def test_optional_volume_and_zero_prices_are_numerically_checked():
    rows = candles(60)
    rows[0].update(open=0, high=0, low=0, close=0, volume=0)
    report = assess_completed_m1(rows, 300)
    assert report['ohlc_invariants_checked']
    assert report['price_side'] == 'UNVERIFIED'
