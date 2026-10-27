"""Offline contract-grid and stressed-risk review; never authorizes any order.

All contract specifications, quotes and account values are untrusted declarations.
This module performs no I/O, authentication, persistence or execution.
"""
from decimal import Decimal, localcontext
import hashlib
import json
import re

NUMERIC = (
    'quantity', 'min_quantity', 'max_quantity', 'quantity_step', 'price_tick',
    'entry_price', 'stop_price', 'stressed_exit_price', 'quote_bid', 'quote_ask',
    'point_value_cash', 'estimated_cost_cash', 'equity_cash',
    'existing_notional_cash', 'existing_margin_cash', 'existing_reserved_risk_cash',
    'daily_realized_pnl_cash', 'daily_unrealized_pnl_cash',
    'max_position_loss_cash', 'max_daily_loss_cash', 'max_gross_leverage',
    'margin_rate_percent', 'max_spread_bps',
)
IDENTITIES = (
    'account_type', 'account_alias', 'instrument', 'contract_id',
    'quote_provider', 'quote_id', 'currency', 'contract_currency',
    'direction', 'client_order_id',
)
TIMES = ('contract_spec_observed_at_ms', 'quote_observed_at_ms', 'quote_received_at_ms')
FIELDS = frozenset(NUMERIC + IDENTITIES + TIMES + ('min_stop_ticks',))
MAX_TIME = 8_640_000_000_000_000
PATTERN = re.compile(r'-?(?:0|[1-9][0-9]{0,14})(?:\\.[0-9]{1,8})?\\Z')
ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\\Z')
NONNEGATIVE = frozenset((
    'estimated_cost_cash', 'existing_notional_cash', 'existing_margin_cash',
    'existing_reserved_risk_cash',
))
SIGNED = frozenset(('daily_realized_pnl_cash', 'daily_unrealized_pnl_cash'))


def _decimal(value, name):
    if not isinstance(value, str) or not PATTERN.fullmatch(value):
        raise ValueError(f'{name}: expected bounded plain decimal string')
    result = Decimal(value)
    if name not in SIGNED and (result < 0 or (result == 0 and name not in NONNEGATIVE)):
        raise ValueError(f'{name}: must be positive or nonnegative')
    return result


def _grid(value, increment):
    return (value / increment) == (value / increment).to_integral_value()


def evaluate_contract_order(declaration, *, now_ms):
    """Check declared contract grids, quote freshness, and stressed risk.

    Returns HOLD_RECONCILIATION even if all structural checks pass.
    """
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_TIME:
        raise ValueError('Invalid trusted clock')
    if not isinstance(declaration, dict) or set(declaration) != FIELDS:
        raise ValueError('Exactly the declared contract-review schema is required')
    d = {}
    for name in NUMERIC:
        d[name] = _decimal(declaration[name], name)
    for name in IDENTITIES:
        value = declaration[name]
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            raise ValueError(f'{name}: invalid identifier')
        d[name] = value
    for name in TIMES:
        value = declaration[name]
        if type(value) is not int or not 0 <= value <= MAX_TIME:
            raise ValueError(f'{name}: invalid timestamp')
        d[name] = value
    ticks = declaration['min_stop_ticks']
    if type(ticks) is not int or not 1 <= ticks <= 10000:
        raise ValueError('min_stop_ticks: invalid bound')
    d['min_stop_ticks'] = ticks
    if d['currency'] not in ('GBP', 'USD', 'EUR') or d['contract_currency'] not in ('GBP', 'USD', 'EUR'):
        raise ValueError('Unsupported currency declaration')
    if d['direction'] not in ('BUY', 'SELL'):
        raise ValueError('Unsupported direction')
    if d['account_type'] not in ('Trading212-Invest', 'Trading212-StocksISA', 'Trading212-CFD', 'OFFLINE-PAPER'):
        raise ValueError('Unsupported account type')
    if d['margin_rate_percent'] > 100 or d['max_spread_bps'] > 10000:
        raise ValueError('Invalid percentage cap')

    c = {}
    c['documented_public_api_account'] = d['account_type'] in ('Trading212-Invest', 'Trading212-StocksISA')
    c['cash_account_buy_only'] = d['direction'] == 'BUY'
    c['same_account_contract_currency'] = d['currency'] == d['contract_currency']
    c['contract_spec_fresh'] = d['contract_spec_observed_at_ms'] <= now_ms and now_ms - d['contract_spec_observed_at_ms'] <= 3600000
    c['quote_timestamp_order'] = d['quote_observed_at_ms'] <= d['quote_received_at_ms'] <= now_ms
    c['quote_fresh'] = c['quote_timestamp_order'] and now_ms - d['quote_observed_at_ms'] <= 3000
    c['transport_lag'] = c['quote_timestamp_order'] and d['quote_received_at_ms'] - d['quote_observed_at_ms'] <= 1000
    c['quantity_limits'] = d['min_quantity'] <= d['quantity'] <= d['max_quantity'] and d['min_quantity'] <= d['max_quantity']
    with localcontext() as ctx:
        ctx.prec = 80
        c['quantity_grid'] = _grid(d['quantity'], d['quantity_step'])
        c['quantity_minimum_grid'] = _grid(d['min_quantity'], d['quantity_step'])
        c['entry_price_grid'] = _grid(d['entry_price'], d['price_tick'])
        c['stop_price_grid'] = _grid(d['stop_price'], d['price_tick'])
        c['uncrossed_quote'] = d['quote_bid'] < d['quote_ask']
        spread = (d['quote_ask'] / d['quote_bid'] - 1) * 10000
        c['spread_ceiling'] = c['uncrossed_quote'] and d['max_spread_bps'] <= 100 and spread <= d['max_spread_bps']
        is_buy = d['direction'] == 'BUY'
        c['entry_executable_side'] = d['entry_price'] >= d['quote_ask'] if is_buy else d['entry_price'] <= d['quote_bid']
        c['stop_correct_side'] = d['stop_price'] < d['entry_price'] if is_buy else d['stop_price'] > d['entry_price']
        c['stop_not_already_breached'] = d['quote_bid'] > d['stop_price'] if is_buy else d['quote_ask'] < d['stop_price']
        c['minimum_stop_distance'] = abs(d['entry_price'] - d['stop_price']) >= d['min_stop_ticks'] * d['price_tick']
        c['stressed_exit_beyond_stop'] = d['stressed_exit_price'] < d['stop_price'] if is_buy else d['stressed_exit_price'] > d['stop_price']
        adverse_exit = min(d['stressed_exit_price'], d['quote_bid']) if is_buy else max(d['stressed_exit_price'], d['quote_ask'])
        loss = abs(d['entry_price'] - adverse_exit) * d['quantity'] * d['point_value_cash'] + d['estimated_cost_cash']
        notional = d['entry_price'] * d['quantity'] * d['point_value_cash']
        margin = notional * d['margin_rate_percent'] / 100
        stressed_equity = d['equity_cash'] - d['existing_reserved_risk_cash'] - loss
        effective_daily = (d['daily_realized_pnl_cash'] + min(d['daily_unrealized_pnl_cash'], Decimal(0))
                           - d['existing_reserved_risk_cash'] - loss)
        c['policy_loss_ceiling'] = d['max_position_loss_cash'] <= d['equity_cash'] * Decimal('0.05') and d['max_daily_loss_cash'] <= d['equity_cash'] * Decimal('0.10')
        c['position_stressed_loss'] = loss > 0 and loss <= d['max_position_loss_cash'] <= d['max_daily_loss_cash']
        c['daily_loss_circuit_breaker'] = effective_daily > -d['max_daily_loss_cash']
        c['cash_only_margin_policy'] = d['margin_rate_percent'] == 100 and d['max_gross_leverage'] <= 1
        c['stressed_equity_positive'] = stressed_equity > 0
        c['stressed_equity_margin'] = c['stressed_equity_positive'] and d['existing_margin_cash'] + margin <= stressed_equity
        c['stressed_equity_leverage'] = c['stressed_equity_positive'] and d['existing_notional_cash'] + notional <= stressed_equity * d['max_gross_leverage']
        c['cash_funded'] = c['stressed_equity_positive'] and d['existing_notional_cash'] + notional <= stressed_equity

    normalized = {k: (format(v.normalize(), 'f') if isinstance(v, Decimal) else v) for k, v in sorted(d.items())}
    digest = hashlib.sha256(json.dumps({'schema': 'paper-contract-execution-guard-v1', 'declaration': normalized, 'now_ms': now_ms},
                                      sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
    return {
        'schema': 'paper-contract-execution-guard-v1',
        'status': 'HOLD_RECONCILIATION',
        'checks': c, 'failed_checks': [key for key, ok in c.items() if not ok],
        'declared_checks_pass': all(c.values()),
        'stressed_loss_cash': format(loss, 'f'),
        'stressed_equity_cash': format(stressed_equity, 'f'),
        'combined_notional_cash': format(d['existing_notional_cash'] + notional, 'f'),
        'combined_margin_cash': format(d['existing_margin_cash'] + margin, 'f'),
        'review_sha256': digest,
        'contract_spec_authenticated': False, 'quote_authenticated': False,
        'broker_inventory_authenticated': False, 'stop_acknowledged_by_broker': False,
        'order_id_durably_reserved': False, 'human_order_approval_recorded': False,
        'may_execute_paper_order': False, 'may_execute_real_order': False,
        'warnings': [
            'Caller-declared contract grids are not authenticated venue specifications.',
            'No FX conversion, broker reconciliation, order reservation, stop acknowledgement or execution.',
            'Stressed exits cannot guarantee a maximum realized loss across gaps or slippage.',
            'Review SHA-256 is diagnostic, not a signature or owner approval.',
        ],
    }
