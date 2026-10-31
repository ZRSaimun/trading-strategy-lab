"""Disconnected, fail-closed PAPER protective-stop amendment review.

This is an offline diagnostic over untrusted declarations. It does not connect
with a broker, authenticate a stop, persist idempotency, amend orders, or grant
paper/live execution. The caller must provide a trusted server clock.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from hashlib import sha256
import json
import re

_MAX_MS = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")


def _object(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError(f"{label}: expected exact fields")
    return value


def _id(value, label):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label}: invalid identifier")
    return value


def _cash(value, label, *, positive=False):
    if type(value) is not str or not _CASH.fullmatch(value):
        raise ValueError(f"{label}: expected bounded plain decimal string")
    number = Decimal(value)
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"{label}: invalid amount")
    return number


def _integer(value, label, *, maximum=_MAX_MS):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label}: invalid integer")
    return value


def _optional_id(value, label):
    return None if value is None else _id(value, label)


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if type(value) is dict:
        return {key: _canonical(val) for key, val in sorted(value.items())}
    return value


def evaluate_stop_amendment(position, request, quote, controls, *, now_ms):
    """Return REVIEW_ONLY_UNVERIFIED or HOLD_RECONCILIATION; never an order grant.

    An apparently safe review is not sufficient to amend a real or paper stop:
    authenticated broker acknowledgement, atomic reservation and owner-specific
    approval remain external requirements. Any failed check must be reconciled.
    """
    now_ms = _integer(now_ms, 'trusted server time')
    p = _object(position, (
        'account_alias', 'broker', 'instrument', 'provider', 'venue', 'side',
        'quantity', 'entry_price', 'stop_price', 'stressed_exit_price',
        'point_value_cash', 'stop_order_id', 'stop_state', 'revision', 'updated_at_ms',
    ), 'position')
    r = _object(request, (
        'account_alias', 'instrument', 'side', 'quantity', 'new_stop_price',
        'expected_stop_order_id', 'expected_revision', 'amendment_id',
    ), 'request')
    q = _object(quote, (
        'instrument', 'provider', 'venue', 'quote_id', 'sequence',
        'bid', 'ask', 'observed_at_ms', 'received_at_ms',
    ), 'quote')
    c = _object(controls, (
        'max_quote_age_ms', 'max_transport_lag_ms', 'max_spread_bps',
        'previous_quote_id', 'previous_quote_sequence', 'previous_amendment_id',
        'max_amendments_per_minute', 'amendments_in_last_minute',
        'account_equity_cash', 'existing_reserved_risk_cash',
        'daily_realized_pnl_cash', 'daily_unrealized_pnl_cash',
        'max_position_loss_cash', 'max_daily_loss_cash',
        'estimated_exit_cost_cash', 'circuit_latched',
    ), 'controls')
    p = dict(p)
    r = dict(r)
    q = dict(q)
    c = dict(c)
    for label, obj, keys in (
        ('position', p, ('account_alias', 'broker', 'instrument', 'provider', 'venue',
                         'side', 'stop_order_id', 'stop_state')),
        ('request', r, ('account_alias', 'instrument', 'side', 'expected_stop_order_id',
                        'amendment_id')),
        ('quote', q, ('instrument', 'provider', 'venue', 'quote_id')),
    ):
        for key in keys:
            obj[key] = _id(obj[key], f'{label}.{key}')
    for label, obj, keys in (
        ('position', p, ('quantity', 'entry_price', 'stop_price', 'stressed_exit_price', 'point_value_cash')),
        ('request', r, ('quantity', 'new_stop_price')),
        ('quote', q, ('bid', 'ask')),
        ('controls', c, ('max_spread_bps', 'account_equity_cash',
                         'existing_reserved_risk_cash', 'daily_realized_pnl_cash',
                         'daily_unrealized_pnl_cash', 'max_position_loss_cash',
                         'max_daily_loss_cash', 'estimated_exit_cost_cash')),
    ):
        for key in keys:
            obj[key] = _cash(obj[key], f'{label}.{key}', positive=(
                key in ('quantity', 'entry_price', 'stop_price', 'stressed_exit_price',
                        'point_value_cash', 'new_stop_price', 'bid', 'ask',
                        'account_equity_cash', 'max_spread_bps',
                        'max_position_loss_cash', 'max_daily_loss_cash')))
    for label, obj, keys in (
        ('position', p, ('revision', 'updated_at_ms')),
        ('request', r, ('expected_revision',)),
        ('quote', q, ('sequence', 'observed_at_ms', 'received_at_ms')),
        ('controls', c, ('max_quote_age_ms', 'max_transport_lag_ms',
                         'previous_quote_sequence', 'max_amendments_per_minute',
                         'amendments_in_last_minute')),
    ):
        for key in keys:
            obj[key] = _integer(obj[key], f'{label}.{key}')
    c['previous_quote_id'] = _optional_id(c['previous_quote_id'], 'previous quote')
    c['previous_amendment_id'] = _optional_id(c['previous_amendment_id'], 'previous amendment')
    if type(c['circuit_latched']) is not bool:
        raise ValueError('circuit_latched: expected boolean')
    if p['broker'] not in ('Trading212-CFD', 'Trading212-Invest', 'Trading212-StocksISA'):
        raise ValueError('Unknown broker account class')
    if p['side'] not in ('LONG', 'SHORT') or r['side'] not in ('LONG', 'SHORT'):
        raise ValueError('Unknown position side')
    if p['stop_state'] not in ('ACKNOWLEDGED', 'PENDING_REPLACE', 'CANCEL_PENDING',
                              'UNKNOWN', 'REJECTED', 'FILLED'):
        raise ValueError('Unknown stop state')
    if not (100 <= c['max_quote_age_ms'] <= 60000
            and c['max_transport_lag_ms'] <= 60000
            and c['max_spread_bps'] <= 10000
            and 1 <= c['max_amendments_per_minute'] <= 60
            and c['amendments_in_last_minute'] <= 10000):
        raise ValueError('Invalid safety policy')
    if any(c[key] < 0 for key in ('existing_reserved_risk_cash', 'estimated_exit_cost_cash')):
        raise ValueError('Negative risk reservation or exit cost')

    with localcontext() as ctx:
        ctx.prec = 100
        long = p['side'] == 'LONG'
        quote_times_ok = q['observed_at_ms'] <= q['received_at_ms'] <= now_ms
        executable = q['bid'] if long else q['ask']
        spread = (q['ask'] / q['bid'] - 1) * Decimal(10000)
        original_geometry = (p['stressed_exit_price'] < p['stop_price'] if long
                             else p['stressed_exit_price'] > p['stop_price'])
        tighten = (r['new_stop_price'] > p['stop_price'] if long
                   else r['new_stop_price'] < p['stop_price'])
        # A stop already crossed is NOT proof of a fill; quarantine the amendment.
        old_unbreached = (executable > p['stop_price'] if long else executable < p['stop_price'])
        new_unbreached = (executable > r['new_stop_price'] if long else executable < r['new_stop_price'])
        worst_exit = (min(p['stressed_exit_price'], executable) if long
                      else max(p['stressed_exit_price'], executable))
        per_unit_downside = (max(Decimal(0), p['entry_price'] - worst_exit) if long
                             else max(Decimal(0), worst_exit - p['entry_price']))
        stressed_loss = (per_unit_downside * p['quantity'] * p['point_value_cash']
                         + c['estimated_exit_cost_cash'])
        projected_daily = (c['daily_realized_pnl_cash']
                           + min(c['daily_unrealized_pnl_cash'], Decimal(0))
                           - c['existing_reserved_risk_cash'] - stressed_loss)
        checks = {
            'account_and_position_identity': (r['account_alias'] == p['account_alias']
                and r['instrument'] == p['instrument'] and r['side'] == p['side']),
            'exact_quantity_unchanged': r['quantity'] == p['quantity'],
            'stop_id_bound': r['expected_stop_order_id'] == p['stop_order_id'],
            'position_revision_bound': r['expected_revision'] == p['revision'],
            'stop_acknowledged_declaration': p['stop_state'] == 'ACKNOWLEDGED',
            'position_event_not_future': p['updated_at_ms'] <= now_ms,
            'quote_source_identity': (q['instrument'] == p['instrument']
                and q['provider'] == p['provider'] and q['venue'] == p['venue']),
            'uncrossed_quote': q['ask'] > q['bid'],
            'quote_timestamp_order': quote_times_ok,
            'quote_fresh': quote_times_ok and now_ms - q['observed_at_ms'] <= c['max_quote_age_ms'],
            'quote_transport_lag': quote_times_ok and q['received_at_ms'] - q['observed_at_ms'] <= c['max_transport_lag_ms'],
            'quote_after_position_event': q['observed_at_ms'] >= p['updated_at_ms'],
            'spread_within_limit': q['ask'] > q['bid'] and spread <= c['max_spread_bps'],
            'quote_sequence_advanced': q['sequence'] > c['previous_quote_sequence'],
            'quote_id_not_replayed': q['quote_id'] != c['previous_quote_id'],
            'amendment_id_not_replayed': r['amendment_id'] != c['previous_amendment_id'],
            'amendment_rate_below_limit': c['amendments_in_last_minute'] < c['max_amendments_per_minute'],
            'stop_strictly_tightened': tighten,
            'original_stress_geometry': original_geometry,
            'original_stop_not_breached': old_unbreached,
            'proposed_stop_not_breached': new_unbreached,
            'position_loss_within_cap': stressed_loss <= c['max_position_loss_cash'],
            'position_cap_within_daily_cap_and_equity': (
                c['max_position_loss_cash'] <= c['max_daily_loss_cash']
                and c['max_position_loss_cash'] <= c['account_equity_cash']),
            'projected_daily_loss_below_cap': projected_daily > -c['max_daily_loss_cash'],
            'circuit_not_latched': not c['circuit_latched'],
        }
        failed = sorted(key for key, ok in checks.items() if not ok)
        digest = sha256(json.dumps(_canonical({
            'schema': 'paper-stop-amendment-review-v1', 'position': p,
            'request': r, 'quote': q, 'controls': c, 'now_ms': now_ms,
        }), sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()
        return {
            'schema': 'paper-stop-amendment-review-v1',
            'status': 'HOLD_RECONCILIATION' if failed else 'REVIEW_ONLY_UNVERIFIED',
            'checks': checks,
            'failed_checks': failed,
            'stressed_loss_cash': str(stressed_loss),
            'projected_daily_pnl_cash': str(projected_daily),
            'review_sha256': digest,
            'quote_authenticated': False,
            'broker_stop_acknowledged': False,
            'amendment_id_persisted': False,
            'may_execute_paper_order': False,
            'may_execute_real_order': False,
            'requires_human_reconciliation': bool(failed),
            'warnings': [
                'Owner-declared stop and quote are NOT authenticated broker receipts.',
                'Stop amendments are not submitted; no execution or persistence is performed.',
                'A stop may gap, slip, be rejected or remain pending despite an earlier acknowledgement.',
                'A SHA-256 review digest is not a signature, replay lock, or owner approval.',
                'Trading 212 public API does not support CFD account execution.',
            ],
        }
