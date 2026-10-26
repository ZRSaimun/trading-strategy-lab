"""Disconnected market-session/quote continuity review. Never permits orders.

Inputs are caller-declared, not authenticated venue status or broker quotes.
Only an independently authenticated feed with documented sequence semantics can
make these checks meaningful in a future transactional admission workflow.
"""
from decimal import Decimal, localcontext
import hashlib
import json
import re

_MAX_MS = 8_640_000_000_000_000
_MAX_SEQUENCE = 2**53 - 1
_SOURCE_KEYS = frozenset({'account_alias', 'provider', 'venue', 'instrument'})
_COMMON = _SOURCE_KEYS | {'observed_ms', 'received_ms', 'sequence', 'event_id'}
_SESSION_KEYS = _COMMON | {'status'}
_QUOTE_KEYS = _COMMON | {'bid', 'ask'}
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z')
_EVENT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{7,79}\Z')
_DECIMAL = re.compile(r'(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?\Z')
_STATUSES = frozenset({'OPEN', 'CLOSED', 'HALTED', 'AUCTION', 'PREOPEN', 'POSTMARKET', 'UNKNOWN'})


def _int(value, upper):
    return type(value) is int and 0 <= value <= upper


def _price(value):
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError('Invalid bounded plain-decimal price')
    result = Decimal(value)
    if result <= 0 or not result.is_finite():
        raise ValueError('Nonpositive/nonfinite price')
    return result


def _source(value):
    if not isinstance(value, dict) or set(value) != _SOURCE_KEYS:
        raise ValueError('Invalid source fields')
    for key in _SOURCE_KEYS:
        if not isinstance(value[key], str) or not _ID.fullmatch(value[key]):
            raise ValueError('Invalid source identifier')
    return dict(value)


def _event(value, source, *, quote):
    expected = _QUOTE_KEYS if quote else _SESSION_KEYS
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('Incomplete session/quote event')
    if any(value[key] != source[key] for key in _SOURCE_KEYS):
        raise ValueError('Event/source identity mismatch')
    if (not _int(value['observed_ms'], _MAX_MS)
            or not _int(value['received_ms'], _MAX_MS)
            or not _int(value['sequence'], _MAX_SEQUENCE)
            or value['sequence'] == 0
            or not isinstance(value['event_id'], str)
            or not _EVENT_ID.fullmatch(value['event_id'])):
        raise ValueError('Invalid event metadata')
    if quote:
        bid, ask = _price(value['bid']), _price(value['ask'])
        return {**value, 'bid': bid, 'ask': ask}
    if type(value['status']) is not str or value['status'] not in _STATUSES:
        raise ValueError('Invalid market-session status')
    return dict(value)


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def review_paper_market_session(source, session, quote, *, now_ms,
                                previous_session=None, previous_quote=None,
                                max_session_age_ms=10_000, max_quote_age_ms=3_000,
                                max_transport_lag_ms=1_000,
                                max_spread_bps='25'):
    """Return untrusted diagnostics only; status is always HOLD_RECONCILIATION.

    Sequence continuity assumes the future provider supplies consecutive event
    numbers. Without a provider-authenticated snapshot and persistent checkpoint,
    a successful declared check is not evidence of an open tradable session.
    """
    if not _int(now_ms, _MAX_MS):
        raise ValueError('Invalid server clock')
    if (not _int(max_session_age_ms, 10_000) or max_session_age_ms < 100
            or not _int(max_quote_age_ms, 3_000) or max_quote_age_ms < 100
            or not _int(max_transport_lag_ms, 1_000)):
        raise ValueError('Unsafe freshness policy')
    spread_cap = _price(max_spread_bps)
    if spread_cap > 10_000:
        raise ValueError('Spread cap too high')
    src = _source(source)
    s = _event(session, src, quote=False)
    q = _event(quote, src, quote=True)
    if (previous_session is None) != (previous_quote is None):
        raise ValueError('Partial previous checkpoint')
    ps = _event(previous_session, src, quote=False) if previous_session is not None else None
    pq = _event(previous_quote, src, quote=True) if previous_quote is not None else None
    checks = {}
    checks['session_open'] = s['status'] == 'OPEN'
    checks['session_time_order'] = s['observed_ms'] <= s['received_ms'] <= now_ms
    checks['quote_time_order'] = q['observed_ms'] <= q['received_ms'] <= now_ms
    checks['session_fresh'] = checks['session_time_order'] and now_ms - s['observed_ms'] <= max_session_age_ms
    checks['quote_fresh'] = checks['quote_time_order'] and now_ms - q['observed_ms'] <= max_quote_age_ms
    checks['session_transport_ok'] = checks['session_time_order'] and s['received_ms'] - s['observed_ms'] <= max_transport_lag_ms
    checks['quote_transport_ok'] = checks['quote_time_order'] and q['received_ms'] - q['observed_ms'] <= max_transport_lag_ms
    checks['quote_after_session_event'] = q['observed_ms'] >= s['observed_ms']
    checks['uncrossed_quote'] = q['ask'] > q['bid']
    with localcontext() as ctx:
        ctx.prec = 80
        spread = (q['ask'] - q['bid']) / q['bid'] * Decimal('10000')
    checks['spread_within_cap'] = checks['uncrossed_quote'] and spread <= spread_cap
    # Replay checkpoints are not trustworthy merely because their sequence
    # numbers are adjacent. Validate their original timing and price envelope
    # before comparing them with the current declared observations.
    checks['previous_session_time_order'] = bool(
        ps is not None and ps['observed_ms'] <= ps['received_ms'] <= now_ms)
    checks['previous_quote_time_order'] = bool(
        pq is not None and pq['observed_ms'] <= pq['received_ms'] <= now_ms)
    checks['previous_session_transport_ok'] = bool(
        ps is not None and checks['previous_session_time_order']
        and ps['received_ms'] - ps['observed_ms'] <= max_transport_lag_ms)
    checks['previous_quote_transport_ok'] = bool(
        pq is not None and checks['previous_quote_time_order']
        and pq['received_ms'] - pq['observed_ms'] <= max_transport_lag_ms)
    checks['previous_quote_after_session_event'] = bool(
        ps is not None and pq is not None
        and pq['observed_ms'] >= ps['observed_ms'])
    checks['previous_quote_uncrossed'] = bool(
        pq is not None and pq['ask'] > pq['bid'])
    with localcontext() as ctx:
        ctx.prec = 80
        previous_spread = ((pq['ask'] - pq['bid']) / pq['bid'] * Decimal('10000')
                           if pq is not None else None)
    checks['previous_spread_within_cap'] = bool(
        checks['previous_quote_uncrossed'] and previous_spread <= spread_cap)
    checks['complete_prior_checkpoint'] = ps is not None and pq is not None
    checks['session_sequence_contiguous'] = bool(ps is not None and s['sequence'] == ps['sequence'] + 1)
    checks['quote_sequence_contiguous'] = bool(pq is not None and q['sequence'] == pq['sequence'] + 1)
    checks['session_not_replayed'] = bool(ps is not None and s['event_id'] != ps['event_id']
                                          and ps['observed_ms'] <= s['observed_ms']
                                          and ps['received_ms'] <= s['received_ms'])
    checks['quote_not_replayed'] = bool(pq is not None and q['event_id'] != pq['event_id']
                                        and pq['observed_ms'] <= q['observed_ms']
                                        and pq['received_ms'] <= q['received_ms'])
    # A previous event cannot be observed in the future relative to this review.
    checks['previous_events_not_future'] = bool(ps is not None and pq is not None
                                                and ps['received_ms'] <= now_ms
                                                and pq['received_ms'] <= now_ms)
    payload = _canonical({'schema': 'paper-market-session-review-v1', 'source': src,
                          'session': s, 'quote': q, 'previous_session': ps,
                          'previous_quote': pq, 'now_ms': now_ms,
                          'max_session_age_ms': max_session_age_ms,
                          'max_quote_age_ms': max_quote_age_ms,
                          'max_transport_lag_ms': max_transport_lag_ms,
                          'max_spread_bps': spread_cap})
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=True).encode('ascii')).hexdigest()
    return {
        'schema': 'paper-market-session-review-v1',
        'status': 'HOLD_RECONCILIATION',
        'assumption_checks_pass': all(checks.values()),
        'checks': checks,
        'failed_checks': [name for name, passed in checks.items() if not passed],
        'review_sha256': fingerprint,
        'source_sha256': hashlib.sha256(json.dumps(src, sort_keys=True,
                                                  separators=(',', ':')).encode('ascii')).hexdigest(),
        'quote_authenticated': False,
        'session_authenticated': False,
        'may_execute_paper_order': False,
        'may_execute_real_order': False,
        'warning': 'Caller-declared status and quotes are not broker-authenticated; no order permission.',
    }
