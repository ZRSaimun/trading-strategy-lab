"""Offline multi-currency paper-risk stress; no brokerage, orders or approvals.

Every amount and quote is unverified caller input. Conversion is restricted to
an explicit settlement/account FX pair and uses the ASK plus a shock buffer for
liabilities. This deliberately does not net gains or infer broker buying power.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from hashlib import sha256
import json
import re

_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]{0,14})(?:\\.[0-9]{1,8})?\\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\\Z")
_CCY = re.compile(r"[A-Z]{3}\\Z")
_MAX_TIME = 8_640_000_000_000_000
_ACCOUNT_FIELDS = {
    'account_currency', 'equity_cash', 'daily_realized_pnl_cash',
    'daily_unrealized_pnl_cash', 'max_daily_loss_cash',
    'max_total_stressed_loss_cash', 'max_single_stressed_loss_cash',
    'max_gross_leverage', 'max_margin_fraction', 'emergency_latched',
    'max_fx_quote_age_ms', 'max_transport_lag_ms', 'max_spread_bps',
    'fx_shock_bps', 'exposures', 'fx_quotes',
}
_EXPOSURE_FIELDS = {
    'client_order_id', 'instrument', 'settlement_currency', 'state',
    'stressed_loss_settlement', 'gross_notional_settlement',
    'reserved_margin_settlement',
}
_QUOTE_FIELDS = {
    'base_currency', 'quote_currency', 'provider', 'venue', 'quote_id',
    'sequence', 'previous_sequence', 'previous_quote_id', 'bid', 'ask',
    'observed_at_ms', 'received_at_ms',
}


def _exact(value, keys, name):
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f'{name}: missing or unexpected fields')


def _amount(value, name, *, positive=False, maximum=Decimal('1000000000000000')):
    if type(value) is not str or not _AMOUNT.fullmatch(value):
        raise ValueError(f'{name}: bounded plain decimal string required')
    amount = Decimal(value)
    if abs(amount) > maximum or (positive and amount <= 0):
        raise ValueError(f'{name}: outside supported bounds')
    return amount


def _identifier(value, name, pattern=_ID):
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError(f'{name}: invalid identifier')
    return value


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name}: invalid integer')
    return value


def evaluate_paper_fx_liabilities(snapshot: dict, *, now_ms: int) -> dict:
    """Conservatively convert declared liabilities into account currency.

    REVIEW_ONLY_UNVERIFIED never means order authorization. Invalid schemas
    raise ValueError; stale, replayed, ambiguous or unsafe scenarios HOLD.
    """
    _exact(snapshot, _ACCOUNT_FIELDS, 'account')
    _integer(now_ms, 'trusted server time', 0, _MAX_TIME)
    account_ccy = _identifier(snapshot['account_currency'], 'account currency', _CCY)
    if type(snapshot['emergency_latched']) is not bool:
        raise ValueError('emergency_latched: boolean required')
    equity = _amount(snapshot['equity_cash'], 'equity', positive=True)
    realized = _amount(snapshot['daily_realized_pnl_cash'], 'daily realized')
    unrealized = _amount(snapshot['daily_unrealized_pnl_cash'], 'daily unrealized')
    daily_cap = _amount(snapshot['max_daily_loss_cash'], 'daily cap', positive=True)
    total_cap = _amount(snapshot['max_total_stressed_loss_cash'], 'total cap', positive=True)
    single_cap = _amount(snapshot['max_single_stressed_loss_cash'], 'single cap', positive=True)
    leverage_cap = _amount(snapshot['max_gross_leverage'], 'leverage', positive=True, maximum=Decimal('100'))
    margin_fraction = _amount(snapshot['max_margin_fraction'], 'margin fraction', positive=True, maximum=Decimal('1'))
    age_cap = _integer(snapshot['max_fx_quote_age_ms'], 'quote age cap', 100, 60000)
    lag_cap = _integer(snapshot['max_transport_lag_ms'], 'transport lag cap', 0, 60000)
    spread_cap = _amount(snapshot['max_spread_bps'], 'spread cap', positive=True, maximum=Decimal('10000'))
    shock = _amount(snapshot['fx_shock_bps'], 'FX shock', maximum=Decimal('5000'))
    if shock < 0 or margin_fraction > 1 or single_cap > total_cap or total_cap > equity or daily_cap > equity:
        raise ValueError('Invalid conservative risk policy')
    exposures, quotes = snapshot['exposures'], snapshot['fx_quotes']
    if type(exposures) is not list or len(exposures) > 100:
        raise ValueError('Invalid bounded exposures')
    if type(quotes) is not list or len(quotes) > 32:
        raise ValueError('Invalid bounded FX quotes')

    with localcontext() as ctx:
        ctx.prec = 80
        fx = {}
        seen_quotes = set()
        quote_checks = {}
        for q in quotes:
            _exact(q, _QUOTE_FIELDS, 'FX quote')
            base = _identifier(q['base_currency'], 'FX base', _CCY)
            target = _identifier(q['quote_currency'], 'FX quote currency', _CCY)
            _identifier(q['provider'], 'FX provider')
            _identifier(q['venue'], 'FX venue')
            quote_id = _identifier(q['quote_id'], 'FX quote ID')
            prev_id = q['previous_quote_id']
            if prev_id is not None:
                _identifier(prev_id, 'previous FX quote ID')
            bid = _amount(q['bid'], 'FX bid', positive=True)
            ask = _amount(q['ask'], 'FX ask', positive=True)
            seq = _integer(q['sequence'], 'FX sequence', 0, _MAX_TIME)
            prev_seq = _integer(q['previous_sequence'], 'previous FX sequence', 0, _MAX_TIME)
            observed = _integer(q['observed_at_ms'], 'FX observation', 0, _MAX_TIME)
            received = _integer(q['received_at_ms'], 'FX receipt', 0, _MAX_TIME)
            if base == target or target != account_ccy or base in fx or quote_id in seen_quotes:
                raise ValueError('Duplicate, ambiguous or wrong-way FX quote')
            seen_quotes.add(quote_id)
            ordered = observed <= received <= now_ms
            quote_checks[base] = {
                'uncrossed': ask > bid,
                'spread_within_limit': ask > bid and (ask / bid - 1) * 10000 <= spread_cap,
                'time_ordered': ordered,
                'fresh': ordered and now_ms - observed <= age_cap,
                'transport_lag': ordered and received - observed <= lag_cap,
                'sequence_advanced': seq > prev_seq,
                'quote_id_advanced': quote_id != prev_id,
            }
            fx[base] = ask * (1 + shock / 10000)

        seen_orders = set()
        required = set()
        uncertain = False
        single_loss_ok = True
        total_loss = Decimal(0)
        total_notional = Decimal(0)
        total_margin = Decimal(0)
        for e in exposures:
            _exact(e, _EXPOSURE_FIELDS, 'exposure')
            oid = _identifier(e['client_order_id'], 'client order ID')
            _identifier(e['instrument'], 'instrument')
            ccy = _identifier(e['settlement_currency'], 'settlement currency', _CCY)
            state = e['state']
            if type(state) is not str or state not in ('OPEN', 'PENDING', 'UNKNOWN', 'CANCEL_PENDING'):
                raise ValueError('Invalid or terminal exposure state')
            if oid in seen_orders:
                raise ValueError('Duplicate client order ID')
            seen_orders.add(oid)
            uncertain |= state in ('UNKNOWN', 'CANCEL_PENDING')
            loss = _amount(e['stressed_loss_settlement'], 'stressed loss')
            notional = _amount(e['gross_notional_settlement'], 'gross notional')
            margin = _amount(e['reserved_margin_settlement'], 'reserved margin')
            if min(loss, notional, margin) < 0:
                raise ValueError('Negative declared liability')
            if ccy != account_ccy:
                required.add(ccy)
            rate = Decimal(1) if ccy == account_ccy else fx.get(ccy)
            if rate is None:
                # Missing FX is a hold, not permission to silently drop exposure.
                continue
            converted_loss = loss * rate
            total_loss += converted_loss
            total_notional += notional * rate
            total_margin += margin * rate
            single_loss_ok &= converted_loss <= single_cap

        coverage = required == set(fx)
        all_fx_valid = all(all(v.values()) for v in quote_checks.values())
        stressed_equity = equity - total_loss
        daily_headroom = daily_cap + realized + min(unrealized, Decimal(0))
        checks = {
            'emergency_circuit_clear': not snapshot['emergency_latched'],
            'all_order_outcomes_known': not uncertain,
            'exact_fx_coverage': coverage,
            'all_fx_quotes_safe': all_fx_valid,
            'single_loss_within_limit': coverage and single_loss_ok,
            'aggregate_loss_within_limit': coverage and total_loss <= total_cap,
            'daily_loss_within_limit': coverage and total_loss <= daily_headroom,
            'stressed_equity_positive': coverage and stressed_equity > 0,
            'stressed_gross_leverage_within_limit': coverage and stressed_equity > 0
                and total_notional <= stressed_equity * leverage_cap,
            'stressed_margin_within_limit': coverage and stressed_equity > 0
                and total_margin <= stressed_equity * margin_fraction,
        }
        status = 'REVIEW_ONLY_UNVERIFIED' if all(checks.values()) else 'HOLD_RECONCILIATION'
        # Fingerprint is a diagnostic, not proof of consent or source authenticity.
        digest = sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=True).encode('utf-8')).hexdigest()
        return {
            'status': status,
            'checks': checks,
            'failed_checks': [k for k, ok in checks.items() if not ok],
            'total_stressed_loss_cash': str(total_loss) if coverage else None,
            'total_gross_notional_cash': str(total_notional) if coverage else None,
            'total_reserved_margin_cash': str(total_margin) if coverage else None,
            'stressed_equity_cash': str(stressed_equity) if coverage else None,
            'fx_quote_checks': quote_checks,
            'diagnostic_sha256': digest,
            'fx_source_authenticated': False,
            'broker_inventory_authenticated': False,
            'durable_risk_reservation': False,
            'human_order_confirmation_verified': False,
            'may_execute_paper_order': False,
            'may_execute_real_order': False,
            'warnings': [
                'Untrusted owner-declared amounts and FX prices; no broker verification.',
                'Direct FX pairs only. ASK plus shock is a conservative liability scenario, not a guaranteed conversion.',
                'FX quote sequence history and identifiers require independent durable checkpoints.',
                'No live or demo orders, journal writes, persistent reservations or approval are performed.',
            ],
        }
