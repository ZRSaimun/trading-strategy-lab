"""Synthetic, disconnected account-wide paper exposure tests."""
from copy import deepcopy
import pytest

from app.paper_account_exposure_guard import evaluate_paper_account_exposure as audit

NOW = 1_800_000_000_000


def example():
    return {
        'account_id': 'paper-acct-001', 'currency': 'GBP',
        'equity_cash': '10000', 'daily_realized_pnl_cash': '-100',
        'daily_unrealized_pnl_cash': '-50', 'max_daily_loss_cash': '500',
        'max_position_loss_cash': '200', 'max_gross_leverage': '2',
        'max_margin_fraction': '0.8', 'max_symbol_notional_cash': '5000',
        'max_open_or_pending_orders': 10, 'max_orders_per_symbol': 3,
        'max_quote_age_ms': 3000, 'max_transport_lag_ms': 1000,
        'max_spread_bps': '20', 'emergency_latched': False,
        'market_session_open': True,
        'exposures': [{
            'client_order_id': 'paper-order-0001', 'instrument': 'XAUUSD',
            'provider': 'DECLARED', 'venue': 'SIM', 'state': 'PENDING',
            'side': 'LONG', 'quantity': '1', 'entry_price': '2002',
            'stop_price': '1980', 'stressed_exit_price': '1970',
            'point_value_cash': '1', 'estimated_total_cost_cash': '5',
            'margin_rate_percent': '5', 'bid': '1999', 'ask': '2001',
            'quote_observed_at_ms': NOW-500, 'quote_received_at_ms': NOW-400,
        }],
    }


def run(snapshot):
    return audit(snapshot, now_ms=NOW)


def test_nominal_scenario_still_denies_every_execution_mode():
    out = run(example())
    assert out['status'] == 'ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED'
    assert out['aggregate_stressed_loss_cash'] == '37'
    assert out['projected_daily_downside_cash'] == '187'
    assert out['may_execute_paper_order'] is False
    assert out['may_execute_real_order'] is False
    assert out['quote_authenticated'] is False
    assert out['risk_reservations_committed'] is False


@pytest.mark.parametrize('key', ['emergency_latched', 'market_session_open'])
def test_latch_and_closed_session_block(key):
    s = example()
    s[key] = True if key == 'emergency_latched' else False
    assert run(s)['status'] == 'HOLD_RECONCILIATION'


@pytest.mark.parametrize('state', ['CANCEL_REQUESTED', 'OUTCOME_UNKNOWN'])
def test_uncertain_order_is_still_counted_at_full_exposure_and_blocks(state):
    s = example()
    s['exposures'][0]['state'] = state
    out = run(s)
    assert out['status'] == 'HOLD_RECONCILIATION'
    assert out['gross_notional_cash'] == '2002'
    assert 'no_uncertain_order_outcomes' in out['failed_checks']


def test_duplicate_order_id_fails_even_with_different_symbols():
    s = example()
    other = deepcopy(s['exposures'][0])
    other['instrument'] = 'XAGUSD'
    s['exposures'].append(other)
    assert 'unique_client_order_ids' in run(s)['failed_checks']


def test_account_order_cap_includes_pending_and_open():
    s = example()
    s['max_open_or_pending_orders'] = 1
    other = deepcopy(s['exposures'][0]); other['client_order_id'] = 'paper-order-0002'
    s['exposures'].append(other)
    assert 'order_count_within_cap' in run(s)['failed_checks']


def test_symbol_count_and_concentration_independently_fail():
    s = example()
    s['max_orders_per_symbol'] = 1
    other = deepcopy(s['exposures'][0]); other['client_order_id'] = 'paper-order-0002'
    s['exposures'].append(other)
    assert 'orders_per_symbol_within_cap' in run(s)['failed_checks']
    s['max_symbol_notional_cash'] = '3000'
    assert 'symbol_notional_within_cap' in run(s)['failed_checks']


def test_position_loss_and_daily_downside_can_fail_independently():
    s = example()
    s['max_position_loss_cash'] = '20'
    assert 'all_position_losses_within_cap' in run(s)['failed_checks']
    s['max_position_loss_cash'] = '200'
    s['daily_realized_pnl_cash'] = '-480'
    assert 'projected_daily_downside_below_cap' in run(s)['failed_checks']


def test_margin_and_leverage_fail_independently():
    s = example(); s['max_margin_fraction'] = '0.005'
    assert 'reserved_margin_within_cap' in run(s)['failed_checks']
    s = example(); s['max_gross_leverage'] = '0.1'
    assert 'gross_leverage_within_cap' in run(s)['failed_checks']


@pytest.mark.parametrize('key,value', [
    ('quote_observed_at_ms', NOW-3001),
    ('quote_received_at_ms', NOW+1),
    ('quote_received_at_ms', NOW-500+1001),
])
def test_stale_future_or_transport_delayed_quote_blocks(key, value):
    s = example(); s['exposures'][0][key] = value
    assert 'all_quotes_fresh_and_uncrossed' in run(s)['failed_checks']


def test_crossed_or_wide_quote_blocks():
    s = example(); s['exposures'][0]['ask'] = '1998'
    assert 'all_quotes_fresh_and_uncrossed' in run(s)['failed_checks']
    s = example(); s['exposures'][0]['ask'] = '2010'
    assert 'all_quotes_fresh_and_uncrossed' in run(s)['failed_checks']


def test_stop_gap_and_pending_entry_direction_block():
    s = example(); s['exposures'][0]['stressed_exit_price'] = '1985'
    assert 'all_stops_and_stress_sides_valid' in run(s)['failed_checks']
    s = example(); s['exposures'][0]['entry_price'] = '2000'
    assert 'all_stops_and_stress_sides_valid' in run(s)['failed_checks']



@pytest.mark.parametrize('side,bid,ask,expected_loss', [
    ('LONG', '1960', '1961', '47'),
    ('SHORT', '2049', '2050', '57'),
])
def test_gap_through_stressed_exit_uses_worse_executable_quote_and_holds(side, bid, ask, expected_loss):
    s = example(); p = s['exposures'][0]
    p['state'] = 'OPEN'
    if side == 'SHORT':
        p.update(side='SHORT', entry_price='1998', stop_price='2020',
                 stressed_exit_price='2030')
    p['bid'] = bid; p['ask'] = ask
    out = run(s)
    assert out['status'] == 'HOLD_RECONCILIATION'
    assert 'no_breached_protective_stops' in out['failed_checks']
    assert out['checks']['all_stops_and_stress_sides_valid']
    assert out['checks']['all_quotes_fresh_and_uncrossed']
    assert out['aggregate_stressed_loss_cash'] == expected_loss
    assert out['exposures'][0]['protective_stop_unbreached'] is False
    assert out['may_execute_paper_order'] is False
    assert out['may_execute_real_order'] is False


@pytest.mark.parametrize('side,bid,ask', [
    ('LONG', '1980', '1981'),
    ('SHORT', '2019', '2020'),
])
def test_stop_touch_alone_requires_reconciliation_even_without_gap(side, bid, ask):
    s = example(); p = s['exposures'][0]
    p['state'] = 'OPEN'
    if side == 'SHORT':
        p.update(side='SHORT', entry_price='1998', stop_price='2020',
                 stressed_exit_price='2030')
    p['bid'] = bid; p['ask'] = ask
    out = run(s)
    assert 'no_breached_protective_stops' in out['failed_checks']
    assert out['aggregate_stressed_loss_cash'] == '37'


def test_fresh_unbreached_stop_is_not_a_broker_fill_attestation():
    out = run(example())
    assert out['checks']['no_breached_protective_stops']
    assert out['exposures'][0]['protective_stop_unbreached'] is True
    assert out['protective_stops_broker_verified'] is False
    assert out['may_execute_real_order'] is False


def test_short_uses_ask_and_giveback_of_unrealized_gain():
    s = example(); p = s['exposures'][0]
    p.update(side='SHORT', entry_price='1998', stop_price='2020',
             stressed_exit_price='2030', bid='1999', ask='2001', state='OPEN')
    out = run(s)
    assert out['status'] == 'ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED'
    assert out['aggregate_stressed_loss_cash'] == '37'
    p['ask'] = '1980'; p['bid'] = '1979'
    assert run(s)['aggregate_stressed_loss_cash'] == '55'


def test_long_giveback_of_unrealized_gain_is_reserved():
    s = example(); p = s['exposures'][0]
    p['state'] = 'OPEN'; p['bid'] = '2010'; p['ask'] = '2011'
    assert run(s)['aggregate_stressed_loss_cash'] == '45'


@pytest.mark.parametrize('field,value', [
    ('quantity', 1.0), ('entry_price', 'NaN'), ('bid', '1e3'),
    ('estimated_total_cost_cash', '-1'), ('margin_rate_percent', '101'),
])
def test_bad_numeric_inputs_fail_closed(field, value):
    s = example(); s['exposures'][0][field] = value
    with pytest.raises(ValueError):
        run(s)


def test_extra_fields_rejected_including_accidental_secrets():
    s = example(); s['api_key'] = 'should-not-be-passed'
    with pytest.raises(ValueError): run(s)
    s = example(); s['exposures'][0]['broker_token'] = 'should-not-be-passed'
    with pytest.raises(ValueError): run(s)


def test_wrong_clock_and_bool_as_int_rejected():
    s = example()
    with pytest.raises(ValueError): audit(s, now_ms=True)
    assert audit(s, now_ms=NOW-1000)["status"] == "HOLD_RECONCILIATION"
    s['max_quote_age_ms'] = True
    with pytest.raises(ValueError): run(s)


def test_malformed_policy_and_unbounded_inventory_rejected():
    s = example(); s['max_position_loss_cash'] = '501'
    with pytest.raises(ValueError): run(s)
    s = example(); s['exposures'] = s['exposures'] * 501
    with pytest.raises(ValueError): run(s)


def test_empty_inventory_does_not_imply_broker_inventory_complete():
    s = example(); s['exposures'] = []
    out = run(s)
    assert out['complete_open_order_inventory_verified'] is False
    assert out['may_execute_paper_order'] is False


def test_quote_age_exact_boundary_is_accepted_but_no_execution():
    s = example(); s['exposures'][0]['quote_observed_at_ms'] = NOW-3000
    s['exposures'][0]['quote_received_at_ms'] = NOW-2000
    out = run(s)
    assert out['checks']['all_quotes_fresh_and_uncrossed']
    assert not out['may_execute_real_order']


def test_stressed_margin_headroom_fails_before_current_margin_cap():
    s = example()
    # Current margin = 100.1, current cap = 101.0; after downside
    # stressed equity = 9813 and cap = 99.1113.
    s['max_margin_fraction'] = '0.0101'
    out = run(s)
    assert out['checks']['reserved_margin_within_cap'] is True
    assert out['checks']['stressed_reserved_margin_within_cap'] is False
    assert out['checks']['stressed_gross_leverage_within_cap'] is True
    assert out['stressed_equity_cash'] == '9813'
    assert out['status'] == 'HOLD_RECONCILIATION'
    assert out['may_execute_paper_order'] is False
    assert out['may_execute_real_order'] is False


def test_stressed_leverage_headroom_fails_before_current_leverage_cap():
    s = example()
    # Current gross = 2002 <= 2020; stressed cap = 9813 * .202.
    s['max_gross_leverage'] = '0.202'
    out = run(s)
    assert out['checks']['gross_leverage_within_cap'] is True
    assert out['checks']['stressed_gross_leverage_within_cap'] is False
    assert out['checks']['stressed_reserved_margin_within_cap'] is True
    assert 'stressed_gross_leverage_within_cap' in out['failed_checks']
    assert out['status'] == 'HOLD_RECONCILIATION'


def test_nonpositive_stressed_equity_never_satisfies_margin_or_leverage():
    s = example()
    s['max_daily_loss_cash'] = '10000'
    s['daily_realized_pnl_cash'] = '-10000'
    out = run(s)
    assert out['stressed_equity_cash'] == '-37'
    assert out['checks']['stressed_reserved_margin_within_cap'] is False
    assert out['checks']['stressed_gross_leverage_within_cap'] is False
    assert out['status'] == 'HOLD_RECONCILIATION'
    assert out['may_execute_real_order'] is False
