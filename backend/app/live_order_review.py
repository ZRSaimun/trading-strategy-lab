"""Disconnected, fail-closed one-order human review packet; NEVER an execution grant.

All figures and quotes are untrusted owner declarations. No broker adapter,
credential, persistence, signing key, network call, or order placement exists here.
"""
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

MONEY_FIELDS = (
    'quantity', 'entry_price', 'stop_price', 'stressed_exit_price',
    'point_value_cash', 'estimated_total_cost_cash', 'account_equity_cash',
    'existing_gross_notional_cash', 'existing_reserved_margin_cash',
    'existing_reserved_risk_cash', 'daily_realized_pnl_cash',
    'daily_unrealized_pnl_cash', 'max_position_loss_cash',
    'max_daily_loss_cash', 'max_gross_leverage', 'margin_rate_percent',
    'quote_bid', 'quote_ask', 'max_spread_bps',
)
TEXT_FIELDS = ('broker', 'account_alias', 'instrument', 'venue', 'quote_provider',
               'direction', 'client_order_id', 'quote_id', 'currency')
TIME_FIELDS = ('quote_observed_at_ms', 'quote_received_at_ms')
EXPECTED_FIELDS = frozenset(MONEY_FIELDS + TEXT_FIELDS + TIME_FIELDS)
BROKERS = {'Trading212-CFD', 'Trading212-Invest', 'Trading212-StocksISA'}
MAX_TIME = 8_640_000_000_000_000


def _money(value, field):
    # String-only: no lossy float conversion, booleans, exponent notation,
    # hidden whitespace, NaN/Infinity, or unbounded precision/scale.
    if not isinstance(value, str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?', value):
        raise ValueError(f'{field}: expected bounded plain decimal string')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f'{field}: invalid decimal') from exc
    if not result.is_finite():
        raise ValueError(f'{field}: non-finite decimal')
    return result


def _identity(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}', value):
        raise ValueError(f'{field}: invalid identifier')
    return value


def _normalize(order):
    if not isinstance(order, dict) or set(order) != EXPECTED_FIELDS:
        raise ValueError('Review input must contain exactly the required fields')
    normalized = {field: _identity(order[field], field) for field in TEXT_FIELDS}
    normalized.update({field: _money(order[field], field) for field in MONEY_FIELDS})
    for field in TIME_FIELDS:
        v = order[field]
        if type(v) is not int or not 0 <= v <= MAX_TIME:
            raise ValueError(f'{field}: invalid UTC epoch milliseconds')
        normalized[field] = v
    if normalized['broker'] not in BROKERS or normalized['direction'] not in ('BUY', 'SELL'):
        raise ValueError('Unsupported broker or direction')
    if not re.fullmatch(r'[A-Z]{3}', normalized['currency']):
        raise ValueError('Invalid account currency')
    for field in MONEY_FIELDS:
        if field in ('daily_realized_pnl_cash', 'daily_unrealized_pnl_cash'):
            continue
        if normalized[field] < 0 or (field not in (
            'estimated_total_cost_cash', 'existing_gross_notional_cash',
            'existing_reserved_margin_cash', 'existing_reserved_risk_cash')
            and normalized[field] == 0):
            raise ValueError(f'{field}: must be positive or nonnegative')
    if normalized['margin_rate_percent'] > 100 or normalized['max_spread_bps'] > 10000:
        raise ValueError('Invalid percentage/basis-point cap')
    return normalized


def _canonical_order(order):
    # Decimal textual representation is normalized so equivalent decimal values
    # have the same digest; the complete input and quote identity are bound.
    return {k: (format(v.normalize(), 'f') if isinstance(v, Decimal) else v)
            for k, v in sorted(order.items())}


def build_review_packet(order, *, now_ms, max_quote_age_ms=3000,
                        max_transport_lag_ms=1000, ttl_ms=30000):
    """Produce a non-executable review; now_ms must be server supplied."""
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_TIME:
        raise ValueError('Invalid trusted server clock')
    if any(type(v) is not int for v in (max_quote_age_ms, max_transport_lag_ms, ttl_ms)):
        raise ValueError('Timing limits must be integers')
    if not 100 <= max_quote_age_ms <= 3000 or not 0 <= max_transport_lag_ms <= 1000 or not 1000 <= ttl_ms <= 60000:
        raise ValueError('Invalid timing policy')
    if now_ms + ttl_ms > MAX_TIME:
        raise ValueError('Review expiry overflow')
    o = _normalize(order)
    checks = {}
    checks['official_api_account_supported'] = o['broker'] != 'Trading212-CFD'
    checks['cash_account_buy_only'] = (o['broker'] == 'Trading212-CFD' or o['direction'] == 'BUY')
    checks['quote_timestamp_order'] = (o['quote_observed_at_ms'] <= o['quote_received_at_ms'] <= now_ms)
    checks['quote_fresh'] = (checks['quote_timestamp_order'] and now_ms - o['quote_observed_at_ms'] <= max_quote_age_ms)
    checks['transport_lag_ok'] = (checks['quote_timestamp_order'] and o['quote_received_at_ms'] - o['quote_observed_at_ms'] <= max_transport_lag_ms)
    checks['uncrossed_quote'] = o['quote_ask'] > o['quote_bid']
    checks['correct_stop_side'] = (o['stop_price'] < o['entry_price'] if o['direction'] == 'BUY'
                                   else o['stop_price'] > o['entry_price'])
    checks['stressed_exit_worse_than_stop'] = (o['stressed_exit_price'] < o['stop_price'] if o['direction'] == 'BUY'
                                               else o['stressed_exit_price'] > o['stop_price'])
    checks['entry_not_better_than_quote'] = (o['entry_price'] >= o['quote_ask'] if o['direction'] == 'BUY'
                                             else o['entry_price'] <= o['quote_bid'])
    # A declared entry far beyond the quoted executable side must not look
    # acceptable solely because the owner also declares a large equity budget.
    # One percent is a conservative OFFLINE sanity ceiling, not a broker fill
    # tolerance or evidence that the quote is genuine.
    checks['declared_entry_deviation_at_most_100bps'] = (
        o['quote_ask'] <= o['entry_price'] <= o['quote_ask'] * Decimal('1.01')
        if o['direction'] == 'BUY'
        else o['quote_bid'] * Decimal('0.99') <= o['entry_price'] <= o['quote_bid'])
    # A touched protective stop is a reconciliation hold, not a fill guarantee.
    checks['protective_stop_not_breached'] = (
        o['quote_bid'] > o['stop_price'] if o['direction'] == 'BUY'
        else o['quote_ask'] < o['stop_price'])
    with localcontext() as ctx:
        ctx.prec = 80
        spread = (o['quote_ask'] / o['quote_bid'] - 1) * 10000
        checks['spread_within_cap'] = checks['uncrossed_quote'] and spread <= o['max_spread_bps']
        notional = o['entry_price'] * o['quantity'] * o['point_value_cash']
        margin = notional * o['margin_rate_percent'] / 100
        # Price downside at the worse of declared stress and executable quote.
        adverse_exit = (min(o['stressed_exit_price'], o['quote_bid'])
                        if o['direction'] == 'BUY'
                        else max(o['stressed_exit_price'], o['quote_ask']))
        loss = (abs(o['entry_price'] - adverse_exit) * o['quantity']
                * o['point_value_cash'] + o['estimated_total_cost_cash'])
        combined_notional = o['existing_gross_notional_cash'] + notional
        combined_margin = o['existing_reserved_margin_cash'] + margin
        # Do not let declared same-day profits replenish a hard daily risk
        # budget: only realized/unrealized losses reduce remaining capacity.
        effective_daily = (min(o['daily_realized_pnl_cash'], Decimal(0))
                           + min(o['daily_unrealized_pnl_cash'], Decimal(0))
                           - o['existing_reserved_risk_cash'] - loss)
        # Conservative non-relaxable bounds for this offline review surface.
        # These are NOT a broker risk policy, nor guarantees against gap losses.
        checks['declared_position_budget_at_most_5pct_equity'] = (
            o['max_position_loss_cash'] * 100 <= o['account_equity_cash'] * 5)
        checks['declared_daily_budget_at_most_10pct_equity'] = (
            o['max_daily_loss_cash'] * 100 <= o['account_equity_cash'] * 10)
        checks['declared_leverage_policy_at_most_5x'] = (
            o['max_gross_leverage'] <= Decimal('5'))
        checks['declared_spread_policy_at_most_100bps'] = (
            o['max_spread_bps'] <= Decimal('100'))
        checks['per_position_loss_cap'] = loss > 0 and loss <= o['max_position_loss_cash']
        checks['position_cap_within_daily_cap_and_equity'] = (o['max_position_loss_cash'] <= o['max_daily_loss_cash']
                                                               and o['max_position_loss_cash'] <= o['account_equity_cash'])
        checks['projected_daily_loss_below_cap'] = effective_daily > -o['max_daily_loss_cash']
        checks['portfolio_margin_within_equity'] = combined_margin <= o['account_equity_cash']
        checks['portfolio_leverage_within_cap'] = combined_notional <= o['account_equity_cash'] * o['max_gross_leverage']
        stressed_equity = o['account_equity_cash'] - loss
        checks['stressed_equity_positive'] = stressed_equity > 0
        checks['stressed_portfolio_margin_within_equity'] = (
            stressed_equity > 0 and combined_margin <= stressed_equity)
        checks['stressed_portfolio_leverage_within_cap'] = (
            stressed_equity > 0 and combined_notional <= stressed_equity * o['max_gross_leverage'])
        # A cash account must cover declared round-trip costs as well as gross
        # purchase exposure; leverage/margin checks alone do not reserve fees.
        checks['cash_account_fully_funded'] = (o['broker'] == 'Trading212-CFD'
                                                 or combined_notional + o['estimated_total_cost_cash']
                                                 <= o['account_equity_cash'])
        # Invest and Stocks ISA are unleveraged cash accounts. A lower
        # owner-declared margin rate understates the stressed cash requirement
        # even when the separate purchase-funding check happens to pass.
        checks['cash_account_full_margin_policy'] = (
            o['broker'] == 'Trading212-CFD'
            or o['margin_rate_percent'] == Decimal('100'))
    canonical = _canonical_order(o)
    digest_input = {'schema': 'live-order-review-v1', 'order': canonical,
                    'issued_at_ms': now_ms, 'expires_at_ms': now_ms + ttl_ms,
                    'max_quote_age_ms': max_quote_age_ms,
                    'max_transport_lag_ms': max_transport_lag_ms}
    digest = hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=True).encode('ascii')).hexdigest()
    return {'schema': 'live-order-review-v1', 'review_sha256': digest,
            'issued_at_ms': now_ms, 'expires_at_ms': now_ms + ttl_ms,
            'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
            'assumption_checks_pass': all(checks.values()),
            'stressed_loss_cash': format(loss, 'f'),
            'combined_notional_cash': format(combined_notional, 'f'),
            'combined_margin_cash': format(combined_margin, 'f'),
            'projected_daily_pnl_cash': format(effective_daily, 'f'),
            'quote_authenticated': False, 'account_authenticated': False,
            'order_id_reserved': False, 'owner_identity_authenticated': False,
            'owner_approval_recorded': False,
            'may_execute_paper_order': False, 'may_execute_real_order': False,
            'warnings': [
                'Untrusted declarations; no broker-authenticated quote, balance, positions or market session.',
                'SHA-256 review fingerprint is NOT a signature, approval, or one-time execution token.',
                'Recalculate on any quote/order/policy change; real execution is disabled.',
                'Stop orders can slip or gap beyond the stressed exit; this is not a maximum loss guarantee.',
            ]}



def _same_review_payload(received, expected):
    """Compare the typed packet schema, not JSON-coerced representations.

    JSON encoding would silently equate tuples with arrays, and can recurse
    indefinitely on malformed nested values. The review packet has a fixed
    shallow schema: check flags are booleans and diagnostic lists are strings.
    Calculated cash amounts alone permit equivalent decimal renderings.
    """
    amount_keys = ('stressed_loss_cash', 'combined_notional_cash',
                   'combined_margin_cash', 'projected_daily_pnl_cash')
    if type(received) is not dict or set(received) != set(expected):
        return False
    for key, wanted in expected.items():
        value = received[key]
        if key in amount_keys:
            if (type(value) is not str or len(value) > 160
                    or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value)
                    or Decimal(value) != Decimal(wanted)):
                return False
        elif key == 'checks':
            if type(value) is not dict or set(value) != set(wanted):
                return False
            if any(type(value[name]) is not bool or value[name] is not flag
                   for name, flag in wanted.items()):
                return False
        elif key in ('failed_checks', 'warnings'):
            if (type(value) is not list or len(value) != len(wanted)
                    or any(type(item) is not str or item != expected_item
                           for item, expected_item in zip(value, wanted))):
                return False
        elif type(value) is not type(wanted) or value != wanted:
            return False
    return True

def compare_review(packet, revised_order, *, now_ms, max_quote_age_ms=3000,
                   max_transport_lag_ms=1000):
    """Detect expired/changed reviews, never grant execution on a match."""
    digest = packet.get('review_sha256') if isinstance(packet, dict) else None
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set('0123456789abcdef'):
        raise ValueError('Invalid review fingerprint')
    issued = packet.get('issued_at_ms')
    expires = packet.get('expires_at_ms')
    if type(issued) is not int or type(expires) is not int or expires <= issued or expires - issued > 60000:
        raise ValueError('Invalid review timing')
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_TIME:
        raise ValueError('Invalid server clock')
    current = build_review_packet(revised_order, now_ms=issued,
                                  ttl_ms=expires-issued,
                                  max_quote_age_ms=max_quote_age_ms,
                                  max_transport_lag_ms=max_transport_lag_ms)
    # A matching input fingerprint alone does not protect the unsigned packet's
    # displayed checks, risk amounts or execution flags from local modification.
    # Compare the entire deterministic packet against a fresh recomputation.
    # This is consistency validation, NOT broker authenticity or a signature.
    matches = current['review_sha256'] == digest and _same_review_payload(packet, current)
    # An unchanged order can still have a quote that became stale after the
    # packet was issued. Re-evaluate the timestamp gate against CURRENT time.
    observed = revised_order['quote_observed_at_ms']
    received = revised_order['quote_received_at_ms']
    quote_fresh_now = (observed <= received <= now_ms
                       and now_ms - observed <= max_quote_age_ms
                       and received - observed <= max_transport_lag_ms)
    valid_now = (matches and issued <= now_ms < expires
                 and current['assumption_checks_pass'] and quote_fresh_now)
    return {'review_matches_exact_intent': matches,
            'review_not_expired': issued <= now_ms < expires,
            'quote_still_fresh': quote_fresh_now,
            'assumption_checks_pass': current['assumption_checks_pass'] and quote_fresh_now,
            'requires_new_human_review': not valid_now,
            'may_execute_real_order': False, 'may_execute_paper_order': False}
