"""Deterministic disconnected paper-stop safety regressions; no broker fixtures."""
from copy import deepcopy
import pytest

from app.paper_stop_amendment_guard import evaluate_stop_amendment

NOW = 1_800_000_000_000


def inputs(side='LONG'):
    is_long = side == 'LONG'
    position = {
        'account_alias': 'paper-one', 'broker': 'Trading212-CFD',
        'instrument': 'XAUUSD', 'provider': 'synthetic', 'venue': 'paper',
        'side': side, 'quantity': '2', 'entry_price': '100',
        'stop_price': '90' if is_long else '110',
        'stressed_exit_price': '85' if is_long else '115',
        'point_value_cash': '1', 'stop_order_id': 'stop-01',
        'stop_state': 'ACKNOWLEDGED', 'revision': 4,
        'updated_at_ms': NOW - 2000,
    }
    request = {
        'account_alias': 'paper-one', 'instrument': 'XAUUSD',
        'side': side, 'quantity': '2',
        'new_stop_price': '95' if is_long else '105',
        'expected_stop_order_id': 'stop-01',
        'expected_revision': 4, 'amendment_id': 'amend-02',
    }
    quote = {
        'instrument': 'XAUUSD', 'provider': 'synthetic', 'venue': 'paper',
        'quote_id': 'q-02', 'sequence': 5,
        'bid': '100', 'ask': '101',
        'observed_at_ms': NOW - 500, 'received_at_ms': NOW - 200,
    }
    controls = {
        'max_quote_age_ms': 3000, 'max_transport_lag_ms': 1000,
        'max_spread_bps': '200', 'previous_quote_id': 'q-01',
        'previous_quote_sequence': 4, 'previous_amendment_id': 'amend-01',
        'max_amendments_per_minute': 3, 'amendments_in_last_minute': 1,
        'account_equity_cash': '10000', 'existing_reserved_risk_cash': '10',
        'daily_realized_pnl_cash': '-20', 'daily_unrealized_pnl_cash': '-10',
        'max_position_loss_cash': '100', 'max_daily_loss_cash': '200',
        'estimated_exit_cost_cash': '2', 'circuit_latched': False,
    }
    return position, request, quote, controls


def run(*args):
    return evaluate_stop_amendment(*args, now_ms=NOW)


@pytest.mark.parametrize('side', ['LONG', 'SHORT'])
def test_safe_review_is_not_execution_grant(side):
    result = run(*inputs(side))
    assert result['status'] == 'REVIEW_ONLY_UNVERIFIED'
    assert result['failed_checks'] == []
    assert result['stressed_loss_cash'] == '32'
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False
    assert result['quote_authenticated'] is False
    assert result['broker_stop_acknowledged'] is False
    assert result['amendment_id_persisted'] is False


@pytest.mark.parametrize('side,new_stop', [
    ('LONG', '89'), ('SHORT', '111'), ('LONG', '90'), ('SHORT', '110'),
])
def test_stop_widening_and_noop_quarantined(side, new_stop):
    p, r, q, c = inputs(side)
    r['new_stop_price'] = new_stop
    result = run(p, r, q, c)
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert 'stop_strictly_tightened' in result['failed_checks']


@pytest.mark.parametrize('side,new_stop', [('LONG', '100'), ('SHORT', '101')])
def test_stop_touch_at_executable_quote_quarantined(side, new_stop):
    p, r, q, c = inputs(side)
    r['new_stop_price'] = new_stop
    assert 'proposed_stop_not_breached' in run(p, r, q, c)['failed_checks']


@pytest.mark.parametrize('side,price', [('LONG', '89'), ('SHORT', '111')])
def test_already_breached_original_stop_is_not_assumed_filled(side, price):
    p, r, q, c = inputs(side)
    q['bid' if side == 'LONG' else 'ask'] = price
    result = run(p, r, q, c)
    assert 'original_stop_not_breached' in result['failed_checks']
    assert result['may_execute_real_order'] is False


@pytest.mark.parametrize('state', ['PENDING_REPLACE', 'CANCEL_PENDING', 'UNKNOWN', 'REJECTED', 'FILLED'])
def test_unconfirmed_stop_state_quarantined(state):
    p, r, q, c = inputs()
    p['stop_state'] = state
    assert 'stop_acknowledged_declaration' in run(p, r, q, c)['failed_checks']


@pytest.mark.parametrize('target,key,value,failed', [
    ('request', 'quantity', '3', 'exact_quantity_unchanged'),
    ('request', 'account_alias', 'other', 'account_and_position_identity'),
    ('request', 'instrument', 'EURUSD', 'account_and_position_identity'),
    ('request', 'side', 'SHORT', 'account_and_position_identity'),
    ('request', 'expected_revision', 3, 'position_revision_bound'),
    ('request', 'expected_stop_order_id', 'other', 'stop_id_bound'),
    ('request', 'amendment_id', 'amend-01', 'amendment_id_not_replayed'),
    ('quote', 'provider', 'other', 'quote_source_identity'),
    ('quote', 'sequence', 4, 'quote_sequence_advanced'),
    ('quote', 'quote_id', 'q-01', 'quote_id_not_replayed'),
    ('quote', 'observed_at_ms', NOW-4000, 'quote_fresh'),
    ('quote', 'received_at_ms', NOW+1, 'quote_timestamp_order'),
    ('quote', 'ask', '99', 'uncrossed_quote'),
    ('controls', 'amendments_in_last_minute', 3, 'amendment_rate_below_limit'),
    ('controls', 'circuit_latched', True, 'circuit_not_latched'),
    ('controls', 'max_position_loss_cash', '10', 'position_loss_within_cap'),
    ('controls', 'max_daily_loss_cash', '60', 'projected_daily_loss_below_cap'),
])
def test_safety_failure_is_fail_closed(target, key, value, failed):
    p, r, q, c = inputs()
    {'position': p, 'request': r, 'quote': q, 'controls': c}[target][key] = value
    result = run(p, r, q, c)
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert failed in result['failed_checks']
    assert result['may_execute_paper_order'] is False


def test_current_bid_below_stress_exit_increases_loss():
    p, r, q, c = inputs()
    q['bid'] = '80'
    result = run(p, r, q, c)
    assert result['stressed_loss_cash'] == '42'
    assert 'original_stop_not_breached' in result['failed_checks']


def test_short_ask_above_stress_exit_increases_loss():
    p, r, q, c = inputs('SHORT')
    q['ask'] = '120'
    result = run(p, r, q, c)
    assert result['stressed_loss_cash'] == '42'
    assert 'original_stop_not_breached' in result['failed_checks']


def test_positive_trailing_stop_can_lock_profit_without_negative_loss():
    p, r, q, c = inputs()
    p['stop_price'] = '102'
    p['stressed_exit_price'] = '101'
    r['new_stop_price'] = '103'
    q['bid'] = '105'
    q['ask'] = '106'
    result = run(p, r, q, c)
    assert result['status'] == 'REVIEW_ONLY_UNVERIFIED'
    assert result['stressed_loss_cash'] == '2'


def test_same_economic_amounts_produce_same_review_digest():
    p, r, q, c = inputs()
    a = run(p, r, q, c)
    r['quantity'] = '2.00'
    q['bid'] = '100.000'
    b = run(p, r, q, c)
    assert a['review_sha256'] == b['review_sha256']


def test_digest_changes_when_stop_changes():
    p, r, q, c = inputs()
    a = run(p, r, q, c)
    r['new_stop_price'] = '96'
    assert a['review_sha256'] != run(p, r, q, c)['review_sha256']


def test_no_mutation_of_inputs():
    args = inputs()
    saved = deepcopy(args)
    run(*args)
    assert args == saved


@pytest.mark.parametrize('target,key,value', [
    ('request', 'quantity', 2.0),
    ('request', 'new_stop_price', 'NaN'),
    ('request', 'new_stop_price', '1e9'),
    ('request', 'new_stop_price', '-1'),
    ('quote', 'sequence', True),
    ('quote', 'bid', 'Infinity'),
    ('quote', 'ask', '0'),
    ('controls', 'circuit_latched', 0),
    ('controls', 'max_amendments_per_minute', 0),
    ('controls', 'existing_reserved_risk_cash', '-1'),
    ('position', 'stop_state', 'UNEXPECTED'),
    ('position', 'side', 'BUY'),
])
def test_invalid_schema_rejected(target, key, value):
    p, r, q, c = inputs()
    {'position': p, 'request': r, 'quote': q, 'controls': c}[target][key] = value
    with pytest.raises(ValueError):
        run(p, r, q, c)


def test_extra_fields_rejected():
    p, r, q, c = inputs()
    r['approve_live_order'] = True
    with pytest.raises(ValueError):
        run(p, r, q, c)


def test_bad_server_clock_rejected():
    with pytest.raises(ValueError):
        evaluate_stop_amendment(*inputs(), now_ms=True)


def test_transport_delay_fails():
    p, r, q, c = inputs()
    q['observed_at_ms'] = NOW - 2900
    q['received_at_ms'] = NOW - 100
    assert 'quote_transport_lag' in run(p, r, q, c)['failed_checks']


def test_quote_cannot_predate_last_stop_event():
    p, r, q, c = inputs()
    p['updated_at_ms'] = NOW - 100
    assert 'quote_after_position_event' in run(p, r, q, c)['failed_checks']
