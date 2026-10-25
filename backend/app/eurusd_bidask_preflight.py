"""Offline, fail-closed paired EUR/USD M1/H1 BID/ASK export inspection.

User-provided bytes are not authenticated provider data or executable broker quotes.
No network, database writes, or order routing.
"""
import csv
import hashlib
import io
import math
import re
from datetime import datetime, timezone

HEADER = ['Etc/UTC', 'Open', 'High', 'Low', 'Close', 'Volume']
MAX_BYTES = 25_000_000
MAX_ROWS = 300_000
INTERVAL_SECONDS = {'M1': 60, 'H1': 3600}
# Require explicitly observed calendar date AND time down to seconds.
# fromisoformat alone supplies omitted time components and truncates fractions
# beyond microseconds, which can manufacture an apparently aligned candle.
TIMESTAMP = re.compile(
    r'[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}'
    r'(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?'
)


def _parse_side(raw, side, interval_seconds):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError(f'{side}: expected bounded CSV bytes')
    try:
        reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        if next(reader, None) != HEADER:
            raise ValueError(f'{side}: expected original Etc/UTC OHLCV header')
        rows = []
        previous = None
        for line, fields in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise ValueError(f'{side}: row budget exceeded')
            if len(fields) != 6:
                raise ValueError(f'{side}: row {line}: expected six columns')
            try:
                timestamp = fields[0].strip()
                if not TIMESTAMP.fullmatch(timestamp):
                    raise ValueError('expected full calendar timestamp YYYY-MM-DD HH:MM:SS '
                                     'with optional microseconds and UTC offset')
                # RFC 3339 -00:00 means the source's UTC offset is unknown,
                # not a verified zero offset; never certify it as UTC.
                if timestamp.endswith('-00:00'):
                    raise ValueError('unknown UTC offset -00:00; cannot certify UTC')
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                # Naive time is UTC only because the exact header declares Etc/UTC.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.utcoffset().total_seconds() != 0 or dt.second or dt.microsecond:
                    raise ValueError('non-UTC or non-minute timestamp')
                stamp = int(dt.timestamp())
                if stamp % interval_seconds:
                    raise ValueError('timestamp not aligned to declared interval')
                if previous is not None and stamp <= previous:
                    raise ValueError('duplicate or backward timestamp')
                o, h, l, c, v = map(float, fields[1:])
                if (not all(math.isfinite(x) for x in (o,h,l,c,v)) or
                    min(o,h,l,c) <= 0 or v < 0 or l > min(o,c) or h < max(o,c) or l > h):
                    raise ValueError('invalid OHLC or volume')
            except (ValueError, OverflowError) as exc:
                raise ValueError(f'{side}: row {line}: {exc}') from exc
            rows.append((stamp, o, h, l, c, v))
            previous = stamp
    except (UnicodeError, csv.Error) as exc:
        raise ValueError(f'{side}: malformed UTF-8 CSV') from exc
    if not rows:
        raise ValueError(f'{side}: zero candles; header-only exports cannot be backtested')
    return rows


def inspect_eurusd_pair(bid_raw, ask_raw, *, interval):
    """Read-only preflight; caller must explicitly declare M1 or H1 cadence."""
    if not isinstance(interval, str) or interval not in INTERVAL_SECONDS:
        raise ValueError('Explicit interval M1 or H1 required; no implicit resampling')
    interval_seconds = INTERVAL_SECONDS[interval]
    bid = _parse_side(bid_raw, 'BID', interval_seconds)
    ask = _parse_side(ask_raw, 'ASK', interval_seconds)
    if len(bid) != len(ask):
        raise ValueError('BID/ASK candle counts differ; no synthetic alignment')
    min_spread, max_spread, gaps = math.inf, -math.inf, 0
    # Only paired, actually observed candle-close spreads enter the quantiles.
    # High/low extrema on two OHLC bars need not occur simultaneously.
    close_spreads_pips = []
    unrepresented_slots, largest_gap_seconds = 0, 0
    # Bounded diagnostic evidence, not a calendar classification or imputation.
    gap_samples = []
    for index, (b, a) in enumerate(zip(bid, ask)):
        if b[0] != a[0]:
            raise ValueError(f'BID/ASK timestamp mismatch at paired row {index+1}')
        if any(b[i] > a[i] for i in (1, 2, 3, 4)):
            raise ValueError(f'crossed BID/ASK OHLC at paired row {index+1}')
        for i in (1, 4):
            spread = a[i] - b[i]
            min_spread = min(min_spread, spread)
            max_spread = max(max_spread, spread)
        close_spreads_pips.append((a[4] - b[4]) * 10000)
        if index:
            elapsed_seconds = b[0] - bid[index-1][0]
            if elapsed_seconds > interval_seconds:
                gaps += 1
                # Counts unrepresented time slots, NOT missing market candles:
                # weekends and closed sessions can legitimately span slots.
                unrepresented_slots += elapsed_seconds // interval_seconds - 1
                largest_gap_seconds = max(largest_gap_seconds, elapsed_seconds)
                if len(gap_samples) < 10:
                    gap_samples.append({
                        'previous_observed_utc': datetime.fromtimestamp(
                            bid[index-1][0], timezone.utc).isoformat(),
                        'next_observed_utc': datetime.fromtimestamp(
                            b[0], timezone.utc).isoformat(),
                        'unrepresented_interval_slots': elapsed_seconds // interval_seconds - 1,
                    })
    close_spreads_pips.sort()
    # Nearest-rank percentiles select observed samples, not interpolated quotes.
    def observed_percentile(percent):
        return round(close_spreads_pips[math.ceil(percent * len(close_spreads_pips)) - 1], 6)

    return {
        'instrument': 'EUR/USD', 'interval': interval, 'interval_seconds': interval_seconds,
        'declared_timebase': 'Etc/UTC',
        'rows': len(bid),
        'first_utc': datetime.fromtimestamp(bid[0][0], timezone.utc).isoformat(),
        'last_utc': datetime.fromtimestamp(bid[-1][0], timezone.utc).isoformat(),
        'observed_gaps_over_interval': gaps,
        'observed_unrepresented_interval_slots': unrepresented_slots,
        'largest_observed_gap_seconds': largest_gap_seconds,
        'observed_gap_samples_first_10': gap_samples,
        'observed_gap_samples_truncated': gaps > len(gap_samples),
        'bid_sha256': hashlib.sha256(bid_raw).hexdigest(),
        'ask_sha256': hashlib.sha256(ask_raw).hexdigest(),
        'observed_open_close_spread_min_pips': round(min_spread * 10000, 6),
        'observed_open_close_spread_max_pips': round(max_spread * 10000, 6),
        'observed_close_spread_sample_count': len(close_spreads_pips),
        'observed_close_spread_p50_pips': observed_percentile(0.50),
        'observed_close_spread_p95_pips': observed_percentile(0.95),
        'volume_classification': 'unverified_source_volume',
        'provider_authenticity': 'unverified_user_supplied_export',
        'broker_executable_quotes': False,
        'licensed_use_verified': False,
        'approved_for_backtest': False,
        'profitable_pattern_proven': False,
        'limitations': [
            'Independent source authenticity and usage-rights review required',
            'OHLC spreads are observations, not broker executable fill costs',
            'Close-only p50/p95 describe sampled candle closes, not tick spreads or Fusion Zero fills',
            'Observed gaps are not necessarily missing market sessions',
            'Unrepresented interval slots can include scheduled market closures, not missing tradeable candles',
            'Declared interval is not authenticated against original export identity',
            'Volume class and first-available news timestamps unverified',
            'No strategy, profitability or trading authorization',
        ],
    }
