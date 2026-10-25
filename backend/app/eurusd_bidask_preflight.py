"""Offline, fail-closed paired EUR/USD M1 BID/ASK export inspection.

User-provided bytes are not authenticated provider data or executable broker quotes.
No network, database writes, or order routing.
"""
import csv
import hashlib
import io
import math
from datetime import datetime, timezone

HEADER = ['Etc/UTC', 'Open', 'High', 'Low', 'Close', 'Volume']
MAX_BYTES = 25_000_000
MAX_ROWS = 300_000


def _parse_side(raw, side):
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
                dt = datetime.fromisoformat(fields[0].strip().replace('Z', '+00:00'))
                # Naive time is UTC only because the exact header declares Etc/UTC.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.utcoffset().total_seconds() != 0 or dt.second or dt.microsecond:
                    raise ValueError('non-UTC or non-minute timestamp')
                stamp = int(dt.timestamp())
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


def inspect_eurusd_pair(bid_raw, ask_raw):
    """Read-only preflight; never treats source declarations as research approval."""
    bid = _parse_side(bid_raw, 'BID')
    ask = _parse_side(ask_raw, 'ASK')
    if len(bid) != len(ask):
        raise ValueError('BID/ASK candle counts differ; no synthetic alignment')
    min_spread, max_spread, gaps = math.inf, -math.inf, 0
    for index, (b, a) in enumerate(zip(bid, ask)):
        if b[0] != a[0]:
            raise ValueError(f'BID/ASK timestamp mismatch at paired row {index+1}')
        if any(b[i] > a[i] for i in (1, 2, 3, 4)):
            raise ValueError(f'crossed BID/ASK OHLC at paired row {index+1}')
        for i in (1, 4):
            spread = a[i] - b[i]
            min_spread = min(min_spread, spread)
            max_spread = max(max_spread, spread)
        if index and b[0] - bid[index-1][0] > 60:
            gaps += 1
    return {
        'instrument': 'EUR/USD', 'interval': 'M1', 'declared_timebase': 'Etc/UTC',
        'rows': len(bid),
        'first_utc': datetime.fromtimestamp(bid[0][0], timezone.utc).isoformat(),
        'last_utc': datetime.fromtimestamp(bid[-1][0], timezone.utc).isoformat(),
        'observed_gaps_over_one_minute': gaps,
        'bid_sha256': hashlib.sha256(bid_raw).hexdigest(),
        'ask_sha256': hashlib.sha256(ask_raw).hexdigest(),
        'observed_open_close_spread_min_pips': round(min_spread * 10000, 6),
        'observed_open_close_spread_max_pips': round(max_spread * 10000, 6),
        'volume_classification': 'unverified_source_volume',
        'provider_authenticity': 'unverified_user_supplied_export',
        'broker_executable_quotes': False,
        'licensed_use_verified': False,
        'approved_for_backtest': False,
        'profitable_pattern_proven': False,
        'limitations': [
            'Independent source authenticity and usage-rights review required',
            'OHLC spreads are observations, not broker executable fill costs',
            'Observed gaps are not necessarily missing market sessions',
            'Volume class and first-available news timestamps unverified',
            'No strategy, profitability or trading authorization',
        ],
    }
