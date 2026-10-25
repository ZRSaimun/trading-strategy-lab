"""Offline, causal-entry bracket outcome bounds for completed M1 OHLC.

Never infers intraminute touch order, authenticates market data, or places orders.
This is a descriptive research tool; not a source of executable CFD fills.
"""
from decimal import Decimal, localcontext
from datetime import datetime, timezone
import re

_PRICE = re.compile(r"[+-]?\d{1,20}(?:\.\d{1,12})?\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
COST_BPS = (0, 5, 10, 20)
MAX_HORIZON = 1440
MAX_PATHS = 100000


def _decimal(value):
    if not isinstance(value, str) or not _PRICE.fullmatch(value):
        raise ValueError('Prices must be bounded exact decimal strings')
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError('Nonfinite price')
    return number


def _identity(path):
    for key in ('path_id', 'instrument', 'provider', 'venue'):
        value = path.get(key)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
            raise ValueError('Exact path and source identity required')
    if not isinstance(path.get('archive_sha256'), str) or not _SHA.fullmatch(path['archive_sha256']):
        raise ValueError('Immutable archive SHA-256 identity required')
    if path.get('price_side') not in ('BID', 'ASK', 'MID'):
        raise ValueError('Explicit historical price side required')


def _time(value):
    return type(value) is int and 0 <= value <= 8640000000 and value % 60 == 0


def _r(entry, exit_price, risk, direction):
    return (exit_price - entry) / risk * (1 if direction == 'LONG' else -1)


def _report(path, status, lower=None, upper=None, reason=None, exit_at=None):
    result = dict(path_id=path['path_id'], status=status, reason=reason, exit_at=exit_at,
                  lower_gross_r=None, upper_gross_r=None, cost_scenarios=[],
                  warning='Historical OHLC bounds only; unknown M1 path order, BID/ASK spread, slippage, commissions, rights and broker executability are not verified.')
    if status == 'CENSORED':
        return result
    entry = _decimal(path['entry'])
    risk = abs(entry - _decimal(path['stop']))
    with localcontext() as ctx:
        ctx.prec = 50
        low = _r(entry, lower, risk, path['direction'])
        high = _r(entry, upper, risk, path['direction'])
        if low > high:
            raise ValueError('Internal bound inversion')
        result['lower_gross_r'] = str(low)
        result['upper_gross_r'] = str(high)
        for bps in COST_BPS:
            # An illustrative round-trip notional-price cost, not a broker quote.
            cost = abs(entry) * Decimal(bps) / Decimal(10000) / risk
            result['cost_scenarios'].append(dict(additional_round_trip_bps=bps,
                                                lower_net_r=str(low - cost), upper_net_r=str(high - cost)))
    return result


def evaluate_path(path):
    """Bracket is frozen at completed signal close; entry at following M1 open.

    All timestamps are UTC minute-open epoch seconds. Incomplete/gapped outcome
    windows are censored (never counted as flat, a win, or a loss).
    """
    if not isinstance(path, dict):
        raise ValueError('Path must be an object')
    _identity(path)
    direction = path.get('direction')
    if direction not in ('LONG', 'SHORT'):
        raise ValueError('Invalid direction')
    signal_at = path.get('signal_at')
    entry_at = path.get('entry_at')
    horizon = path.get('horizon_minutes')
    if not _time(signal_at) or not _time(entry_at) or entry_at != signal_at + 60:
        raise ValueError('Entry must be the next UTC minute after completed signal')
    if type(horizon) is not int or not 1 <= horizon <= MAX_HORIZON:
        raise ValueError('Invalid frozen horizon')
    entry, stop, target = (_decimal(path[k]) for k in ('entry', 'stop', 'target'))
    if entry == 0 or not (stop < entry < target if direction == 'LONG' else target < entry < stop):
        raise ValueError('Entry must lie strictly between predeclared stop and target')
    bars = path.get('bars')
    if not isinstance(bars, list) or len(bars) > horizon:
        raise ValueError('Invalid bounded outcome window')
    # Validate all supplied bars, even those after a bracket touch.
    parsed = []
    previous = None
    for bar in bars:
        if not isinstance(bar, dict) or not _time(bar.get('at')):
            raise ValueError('Invalid UTC minute timestamp')
        at = bar['at']
        if at < entry_at or (previous is not None and at <= previous):
            raise ValueError('Nonmonotonic or pre-entry bar')
        previous = at
        o, h, l, c = (_decimal(bar[k]) for k in ('open', 'high', 'low', 'close'))
        if not (l <= min(o, c) <= max(o, c) <= h):
            raise ValueError('Invalid OHLC envelope')
        parsed.append((at, o, h, l, c))
    if parsed and parsed[0][1] != entry:
        raise ValueError('Entry must equal first observed next-open price')
    for i, (at, o, h, l, _c) in enumerate(parsed):
        if at != entry_at + i * 60:
            return _report(path, 'CENSORED', reason='UNOBSERVED_MINUTE_BEFORE_EXIT')
        if direction == 'LONG':
            if o <= stop:  # Adverse gap: never assume fill at the better stop.
                return _report(path, 'DETERMINATE', o, o, exit_at=at)
            if o >= target:  # Favorable gap is capped at target.
                return _report(path, 'DETERMINATE', target, target, exit_at=at)
            hit_stop, hit_target = l <= stop, h >= target
        else:
            if o >= stop:
                return _report(path, 'DETERMINATE', o, o, exit_at=at)
            if o <= target:
                return _report(path, 'DETERMINATE', target, target, exit_at=at)
            hit_stop, hit_target = h >= stop, l <= target
        if hit_stop and hit_target:
            return _report(path, 'AMBIGUOUS', stop, target, reason='BOTH_LEVELS_TOUCHED_WITH_UNKNOWN_ORDER', exit_at=at)
        if hit_stop:
            return _report(path, 'DETERMINATE', stop, stop, exit_at=at)
        if hit_target:
            return _report(path, 'DETERMINATE', target, target, exit_at=at)
    if len(parsed) != horizon:
        return _report(path, 'CENSORED', reason='INCOMPLETE_HORIZON')
    return _report(path, 'DETERMINATE', parsed[-1][4], parsed[-1][4],
                   reason='HORIZON_CLOSE', exit_at=parsed[-1][0])


def audit_paths(paths):
    """Conservative population accounting; never silently drop censored paths."""
    if not isinstance(paths, list) or len(paths) > MAX_PATHS:
        raise ValueError('Bounded path list required')
    results, ids, source_keys, weeks = [], set(), set(), set()
    for path in paths:
        result = evaluate_path(path)
        if result['path_id'] in ids:
            raise ValueError('Duplicate path ID')
        ids.add(result['path_id'])
        source_keys.add(tuple(path[k] for k in ('instrument', 'provider', 'venue', 'archive_sha256', 'price_side')))
        weeks.add(datetime.fromtimestamp(path['signal_at'], timezone.utc).isocalendar()[:2])
        results.append(result)
    if len(source_keys) > 1:
        raise ValueError('Mixed source identities cannot be pooled')
    counts = {k: sum(r['status'] == k for r in results) for k in ('DETERMINATE', 'AMBIGUOUS', 'CENSORED')}
    # Only complete samples with enough time dispersion qualify for descriptive means.
    eligible = counts['CENSORED'] == 0 and len(results) >= 30 and len(weeks) >= 12
    scenarios = []
    for i, bps in enumerate(COST_BPS):
        lows = [Decimal(r['cost_scenarios'][i]['lower_net_r']) for r in results if r['status'] != 'CENSORED']
        highs = [Decimal(r['cost_scenarios'][i]['upper_net_r']) for r in results if r['status'] != 'CENSORED']
        scenarios.append(dict(additional_round_trip_bps=bps,
                              population_mean_lower_net_r=str(sum(lows) / len(lows)) if eligible else None,
                              population_mean_upper_net_r=str(sum(highs) / len(highs)) if eligible else None))
    return dict(total=len(results), counts=counts, active_utc_weeks=len(weeks),
                status='DESCRIPTIVE_BOUNDS_ONLY' if eligible else 'INSUFFICIENT_OR_CENSORED',
                cost_scenarios=scenarios, paths=results,
                verified_profitability=False, executable_broker_fills=False,
                warning='No archive provenance, licensing, broker spreads, order-book sequence, untouched holdout or prospective edge is certified.')
