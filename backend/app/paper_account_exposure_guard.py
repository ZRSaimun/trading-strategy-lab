"""Read-only, fail-closed PAPER account-wide exposure stress preview.

Every observation is caller-declared and incomplete until independently reconciled
against a supported broker. No orders, credentials, network access or DB writes.
"""
from decimal import Decimal, localcontext
import hashlib
import re

_MAX_MS = 8_640_000_000_000_000
_MAX_CASH = Decimal('1000000000000000')
_DECIMAL = re.compile(r'(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?\Z')
_SIGNED = re.compile(r'-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z')
_SYMBOL = re.compile(r'[A-Za-z0-9._:/+-]{1,64}\Z')
_ACCOUNT_KEYS = {
    'account_id', 'currency', 'equity_cash', 'daily_realized_pnl_cash',
    'daily_unrealized_pnl_cash', 'max_daily_loss_cash', 'max_position_loss_cash',
    'max_gross_leverage', 'max_margin_fraction', 'max_symbol_notional_cash',
    'max_open_or_pending_orders', 'max_orders_per_symbol', 'max_quote_age_ms',
    'max_transport_lag_ms', 'max_spread_bps', 'emergency_latched',
    'market_session_open', 'exposures',
}
_EXPOSURE_KEYS = {
    'client_order_id', 'instrument', 'provider', 'venue', 'state', 'side',
    'quantity', 'entry_price', 'stop_price', 'stressed_exit_price',
    'point_value_cash', 'estimated_total_cost_cash', 'margin_rate_percent',
    'bid', 'ask', 'quote_observed_at_ms', 'quote_received_at_ms',
}


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f'{label} has missing or unexpected fields')


def _decimal(value, name, *, positive=False, signed=False, max_value=_MAX_CASH):
    if type(value) is not str or not (_SIGNED if signed else _DECIMAL).fullmatch(value):
        raise ValueError(f'{name} must be a bounded decimal string')
    number = Decimal(value)
    if abs(number) > max_value or (positive and number <= 0):
        raise ValueError(f'{name} outside supported bounds')
    return number


def _int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'Invalid {name}')
    return value


def _id(value, name, pattern):
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError(f'Invalid {name}')
    return value


def evaluate_paper_account_exposure(snapshot: dict, *, now_ms: int) -> dict:
    """Conservative account-wide hypothetical exposure, never an order gate.

    OPEN and PENDING are both counted at full declared quantity. Uncertain order
    states are also counted at full quantity AND force a reconciliation hold.
    Quotes and account/position completeness are NOT authenticated.
    """
    _exact(snapshot, _ACCOUNT_KEYS, 'Account snapshot')
    _int(now_ms, 'server clock', 0, _MAX_MS)
    account = _id(snapshot['account_id'], 'account alias', _ID)
    if type(snapshot['currency']) is not str or not re.fullmatch(r'[A-Z]{3}', snapshot['currency']):
        raise ValueError('Invalid account currency')
    if type(snapshot['emergency_latched']) is not bool or type(snapshot['market_session_open']) is not bool:
        raise ValueError('Invalid safety latch or market-session state')
    equity = _decimal(snapshot['equity_cash'], 'equity', positive=True)
    realized = _decimal(snapshot['daily_realized_pnl_cash'], 'realized', signed=True)
    unrealized = _decimal(snapshot['daily_unrealized_pnl_cash'], 'unrealized', signed=True)
    daily_cap = _decimal(snapshot['max_daily_loss_cash'], 'daily cap', positive=True)
    position_cap = _decimal(snapshot['max_position_loss_cash'], 'position cap', positive=True)
    leverage = _decimal(snapshot['max_gross_leverage'], 'leverage cap', positive=True, max_value=Decimal('100'))
    margin_fraction = _decimal(snapshot['max_margin_fraction'], 'margin fraction', positive=True, max_value=Decimal('1'))
    symbol_cap = _decimal(snapshot['max_symbol_notional_cash'], 'symbol cap', positive=True)
    max_orders = _int(snapshot['max_open_or_pending_orders'], 'max orders', 1, 500)
    max_per_symbol = _int(snapshot['max_orders_per_symbol'], 'max orders per symbol', 1, 100)
    max_age = _int(snapshot['max_quote_age_ms'], 'quote age policy', 100, 60000)
    max_lag = _int(snapshot['max_transport_lag_ms'], 'transport lag policy', 0, 60000)
    max_spread = _decimal(snapshot['max_spread_bps'], 'spread cap', positive=True, max_value=Decimal('10000'))
    if position_cap > daily_cap or daily_cap > equity:
        raise ValueError('Loss caps must be ordered position <= daily <= equity')
    exposures = snapshot['exposures']
    if type(exposures) is not list or len(exposures) > 500:
        raise ValueError('Invalid bounded exposure list')

    checks = {
        'emergency_latch_clear': not snapshot['emergency_latched'],
        'market_session_open': snapshot['market_session_open'],
        'order_count_within_cap': len(exposures) <= max_orders,
        'unique_client_order_ids': True,
        'no_uncertain_order_outcomes': True,
        'all_quotes_fresh_and_uncrossed': True,
        'all_stops_and_stress_sides_valid': True,
        'all_position_losses_within_cap': True,
        'orders_per_symbol_within_cap': True,
        'symbol_notional_within_cap': True,
        'gross_leverage_within_cap': True,
        'reserved_margin_within_cap': True,
        'projected_daily_downside_below_cap': True,
    }
    seen = set()
    per_symbol = {}
    counts = {}
    details = []
    with localcontext() as ctx:
        ctx.prec = 80
        gross = margin = stressed = Decimal(0)
        for index, row in enumerate(exposures):
            _exact(row, _EXPOSURE_KEYS, f'Exposure {index}')
            order_id = _id(row['client_order_id'], 'client order ID', _ID)
            symbol = _id(row['instrument'], 'instrument', _SYMBOL)
            _id(row['provider'], 'provider', _SYMBOL)
            _id(row['venue'], 'venue', _SYMBOL)
            if row['state'] not in ('OPEN', 'PENDING', 'CANCEL_REQUESTED', 'OUTCOME_UNKNOWN'):
                raise ValueError('Invalid order state')
            if row['side'] not in ('LONG', 'SHORT'):
                raise ValueError('Invalid side')
            if order_id in seen:
                checks['unique_client_order_ids'] = False
            seen.add(order_id)
            counts[symbol] = counts.get(symbol, 0) + 1
            if row['state'] in ('CANCEL_REQUESTED', 'OUTCOME_UNKNOWN'):
                checks['no_uncertain_order_outcomes'] = False
            qty = _decimal(row['quantity'], 'quantity', positive=True)
            entry = _decimal(row['entry_price'], 'entry', positive=True)
            stop = _decimal(row['stop_price'], 'stop', positive=True)
            exit_price = _decimal(row['stressed_exit_price'], 'stressed exit', positive=True)
            point = _decimal(row['point_value_cash'], 'point value', positive=True)
            fees = _decimal(row['estimated_total_cost_cash'], 'costs')
            rate = _decimal(row['margin_rate_percent'], 'margin rate', positive=True, max_value=Decimal('100'))
            bid = _decimal(row['bid'], 'bid', positive=True)
            ask = _decimal(row['ask'], 'ask', positive=True)
            observed = _int(row['quote_observed_at_ms'], 'quote observed', 0, _MAX_MS)
            received = _int(row['quote_received_at_ms'], 'quote received', 0, _MAX_MS)
            time_ok = observed <= received <= now_ms and now_ms - observed <= max_age and received - observed <= max_lag
            spread_ok = ask > bid and ((ask - bid) / bid * Decimal('10000') <= max_spread)
            checks['all_quotes_fresh_and_uncrossed'] &= time_ok and spread_ok
            is_long = row['side'] == 'LONG'
            stop_ok = (exit_price < stop < entry) if is_long else (entry < stop < exit_price)
            # A pending fill may not assume a better entry than the current ask/bid.
            if row['state'] != 'OPEN':
                stop_ok &= entry >= ask if is_long else entry <= bid
            checks['all_stops_and_stress_sides_valid'] &= stop_ok
            # Include the potential give-back of current open unrealized gains.
            mark = bid if is_long else ask
            distance = (max(entry, mark) - exit_price) if is_long else (exit_price - min(entry, mark))
            loss = max(Decimal(0), distance) * qty * point + fees
            # Do not let a cheap historic entry understate current gross exposure.
            notional = max(entry, ask) * qty * point
            assumed_margin = notional * rate / Decimal('100')
            gross += notional
            margin += assumed_margin
            stressed += loss
            per_symbol[symbol] = per_symbol.get(symbol, Decimal(0)) + notional
            checks['all_position_losses_within_cap'] &= 0 < loss <= position_cap
            details.append({
                'client_order_sha256': hashlib.sha256((account + '\0' + order_id).encode('ascii')).hexdigest(),
                'instrument': symbol, 'state': row['state'],
                'stressed_loss_cash': format(loss, 'f'),
                'gross_notional_cash': format(notional, 'f'),
                'assumed_margin_cash': format(assumed_margin, 'f'),
                'quote_policy_pass': bool(time_ok and spread_ok),
                'stop_policy_pass': bool(stop_ok),
            })
        checks['orders_per_symbol_within_cap'] = all(n <= max_per_symbol for n in counts.values())
        checks['symbol_notional_within_cap'] = all(v <= symbol_cap for v in per_symbol.values())
        checks['gross_leverage_within_cap'] = gross <= equity * leverage
        checks['reserved_margin_within_cap'] = margin <= equity * margin_fraction
        # Floating gains cannot offset realized losses or adverse exposure.
        downside = max(Decimal(0), -(realized + min(unrealized, Decimal(0)))) + stressed
        checks['projected_daily_downside_below_cap'] = downside < daily_cap
    passed = all(checks.values())
    return {
        'status': 'ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED' if passed else 'HOLD_RECONCILIATION',
        'checks': checks,
        'failed_checks': sorted(k for k, ok in checks.items() if not ok),
        'gross_notional_cash': format(gross, 'f'),
        'assumed_reserved_margin_cash': format(margin, 'f'),
        'aggregate_stressed_loss_cash': format(stressed, 'f'),
        'projected_daily_downside_cash': format(downside, 'f'),
        'symbol_notional_cash': {k: format(v, 'f') for k, v in sorted(per_symbol.items())},
        'exposures': details,
        'broker_account_authenticated': False,
        'quote_authenticated': False,
        'complete_open_order_inventory_verified': False,
        'protective_stops_broker_verified': False,
        'risk_reservations_committed': False,
        'owner_order_approval_verified': False,
        'may_execute_paper_order': False,
        'may_execute_real_order': False,
        'warnings': [
            'Caller-declared portfolio is not broker-reconciled; omitted orders/positions can invalidate every limit.',
            'Pending and uncertain orders are counted at full quantity; cancellation is not a confirmed release.',
            'Stop losses and stressed exits are scenarios, not guaranteed fills or maximum possible losses.',
            'All values assume verified point-value and account-currency conversion, which this module cannot verify.',
            'No broker API, persistent reservation, human approval, or order sender is connected.',
        ],
    }
