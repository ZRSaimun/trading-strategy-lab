"""Pure, read-only quality observations for completed UTC M1 provider candles.

This is NOT a live-feed monitor, market-calendar completeness claim, quote
attestation, execution quote or entitlement verification.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _utc_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def assess_completed_m1(rows: list[dict], observed_at: int, *, sample_limit: int = 5) -> dict:
    """Assess sorted, closed one-minute bars without filling gaps or mutating rows.

    `observed_at` is the server's receipt/evaluation time, not an exchange time.
    A gap is an observed UTC timestamp difference, NOT proof of missing trading.
    """
    if type(observed_at) is not int or observed_at < 60:
        raise ValueError('A valid server UTC observation time is required')
    if type(sample_limit) is not int or not 0 <= sample_limit <= 20:
        raise ValueError('sample_limit must be an integer from 0 to 20')
    if not isinstance(rows, list) or not rows:
        raise ValueError('At least one completed candle is required')

    previous = None
    gaps = 0
    unobserved = 0
    largest = 0
    samples = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get('time')) is not int:
            raise ValueError('Each candle requires an integer UTC timestamp')
        t = row['time']
        if t < 0 or t % 60:
            raise ValueError('Candle timestamps must be nonnegative UTC minute boundaries')
        if t + 60 > observed_at:
            raise ValueError('Future or incomplete candles cannot be assessed')
        if previous is not None:
            if t <= previous:
                raise ValueError('Duplicate or nonchronological candles cannot be assessed')
            elapsed = t - previous
            if elapsed > 60:
                gap_minutes = elapsed // 60 - 1
                gaps += 1
                unobserved += gap_minutes
                largest = max(largest, gap_minutes)
                if len(samples) < sample_limit:
                    samples.append({
                        'after_utc': _utc_iso(previous),
                        'before_utc': _utc_iso(t),
                        'unobserved_minutes': gap_minutes,
                    })
        previous = t

    last = rows[-1]['time']
    return {
        'assessment': 'OBSERVED_ONLY_HISTORICAL',
        'interval_seconds': 60,
        'observed_at_utc': _utc_iso(observed_at),
        'first_candle_utc': _utc_iso(rows[0]['time']),
        'last_candle_utc': _utc_iso(last),
        'last_candle_close_utc': _utc_iso(last + 60),
        'seconds_since_last_candle_close': observed_at - last - 60,
        'observed_candles': len(rows),
        'observed_timestamp_gaps': gaps,
        'unobserved_minutes_between_candles': unobserved,
        'largest_unobserved_span_minutes': largest,
        'gap_samples': samples,
        'market_calendar_checked': False,
        'source_authenticity_verified': False,
        'provider_entitlement_verified': False,
        'executable_bid_ask_verified': False,
        'live': False,
        'may_execute_order': False,
        'caveat': 'Observed UTC gaps may be market closures, outages, or missing data; no market session or executable spread is inferred.',
    }
