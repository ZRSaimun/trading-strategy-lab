"""Offline synthetic contract metadata and risk tests; no network or orders."""
from copy import deepcopy
import pytest
from app.paper_contract_execution_guard import evaluate_contract_order

NOW = 1790000000000


def candidate(**changes):
    data = dict(
        account_type='Trading212-Invest', account_alias='test-account', instrument='TEST-USD',
        contract_id='test-spec-v1', quote_provider='TEST', quote_id='q-1',
        currency='USD', contract_currency='USD', direction='BUY', client_order_id='order-1',
        contract_spec_observed_at_ms=NOW-10000, quote_observed_at_ms=NOW-200,
        quote_received_at_ms=NOW-100, min_stop_ticks=2,
        quantity='2', min_quantity='0.1', max_quantity='10', quantity_step='0.1',
        price_tick='0.01', entry_price='100.02', stop_price='99',
        stressed_exit_price='98', quote_bid='100', quote_ask='100.02',
        point_value_cash='1', estimated_cost_cash='0.5', equity_cash='1000',
        existing_notional_cash='100', existing_margin_cash='100', existing_reserved_risk_cash='1',
        daily_realized_pnl_cash='-1', daily_unrealized_pnl_cash='-2',
        max_position_loss_cash='10', max_daily_loss_cash='50', max_gross_leverage='1',
        margin_rate_percent='100', max_spread_bps='10',
    )
    data.update(changes)
    return data


def review(**changes):
    return evaluate_contract_order(candidate(**changes), now_ms=NOW)


def test_valid_declared_candidate_is_still_non_executable():
    r = review()
    assert r['declared_checks_pass'] and not r['failed_checks']
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert r['may_execute_real_order'] is False and r['may_execute_paper_order'] is False
    assert r['stressed_loss_cash'] == '4.54'
    assert r['stressed_equity_cash'] == '994.46'
    assert not r['contract_spec_authenticated'] and not r['stop_acknowledged_by_broker']


@pytest.mark.parametrize('change, failed', [
    ({'account_type':'Trading212-CFD'}, 'documented_public_api_account'),
    ({'account_type':'OFFLINE-PAPER'}, 'documented_public_api_account'),
    ({'direction':'SELL', 'entry_price':'100', 'stop_price':'101', 'stressed_exit_price':'102'}, 'cash_account_buy_only'),
    ({'contract_currency':'GBP'}, 'same_account_contract_currency'),
    ({'contract_spec_observed_at_ms':NOW-3600001}, 'contract_spec_fresh'),
    ({'contract_spec_observed_at_ms':NOW+1}, 'contract_spec_fresh'),
    ({'quote_observed_at_ms':NOW-3001}, 'quote_fresh'),
    ({'quote_received_at_ms':NOW+1}, 'quote_timestamp_order'),
    ({'quote_observed_at_ms':NOW-2000}, 'transport_lag'),
    ({'quantity':'0.05'}, 'quantity_limits'),
    ({'quantity':'11'}, 'quantity_limits'),
    ({'quantity':'2.05'}, 'quantity_grid'),
    ({'min_quantity':'0.15'}, 'quantity_minimum_grid'),
    ({'entry_price':'100.025'}, 'entry_price_grid'),
    ({'stop_price':'99.005'}, 'stop_price_grid'),
    ({'quote_bid':'100.02'}, 'uncrossed_quote'),
    ({'quote_ask':'101'}, 'spread_ceiling'),
    ({'max_spread_bps':'101'}, 'spread_ceiling'),
    ({'entry_price':'100'}, 'entry_executable_side'),
    ({'stop_price':'100.01'}, 'stop_not_already_breached'),
    ({'stop_price':'100.02'}, 'stop_correct_side'),
    ({'stop_price':'100.01','min_stop_ticks':2}, 'minimum_stop_distance'),
    ({'stressed_exit_price':'99.5'}, 'stressed_exit_beyond_stop'),
    ({'max_position_loss_cash':'1'}, 'position_stressed_loss'),
    ({'max_position_loss_cash':'60'}, 'policy_loss_ceiling'),
    ({'max_daily_loss_cash':'101'}, 'policy_loss_ceiling'),
    ({'daily_realized_pnl_cash':'-49'}, 'daily_loss_circuit_breaker'),
    ({'margin_rate_percent':'50'}, 'cash_only_margin_policy'),
    ({'max_gross_leverage':'2'}, 'cash_only_margin_policy'),
    ({'existing_margin_cash':'900'}, 'stressed_equity_margin'),
    ({'existing_notional_cash':'900'}, 'stressed_equity_leverage'),
])
def test_fail_closed_cases(change, failed):
    result = review(**change)
    assert failed in result['failed_checks']
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert result['may_execute_real_order'] is False


@pytest.mark.parametrize('change', [
    {'quantity':2}, {'quantity':'1e3'}, {'quantity':'NaN'}, {'quantity':'0'},
    {'quantity':'-1'}, {'quantity':'0.000000001'}, {'quantity':' 2'},
    {'price_tick':'0'}, {'point_value_cash':'0'}, {'existing_margin_cash':'-1'},
    {'min_stop_ticks':True}, {'min_stop_ticks':0}, {'min_stop_ticks':10001},
    {'quote_received_at_ms':True}, {'contract_spec_observed_at_ms':-1},
    {'direction':'HOLD'}, {'currency':'JPY'}, {'client_order_id':'bad order'},
    {'account_type':'UNKNOWN'}, {'margin_rate_percent':'101'},
])
def test_reject_invalid_schema_values(change):
    with pytest.raises(ValueError):
        review(**change)


def test_reject_extra_or_missing_fields_and_invalid_clock():
    d = candidate()
    d['api_secret'] = 'never accept credentials'
    with pytest.raises(ValueError):
        evaluate_contract_order(d, now_ms=NOW)
    d = candidate()
    del d['quote_id']
    with pytest.raises(ValueError):
        evaluate_contract_order(d, now_ms=NOW)
    for clock in (True, -1, '1790000000000'):
        with pytest.raises(ValueError):
            evaluate_contract_order(candidate(), now_ms=clock)


def test_stress_uses_worse_executable_quote_not_optimistic_stop():
    # A quote that has already breached the stop is quarantined, but loss is
    # still computed using the worse current executable price.
    result = review(quote_bid='96', quote_ask='96.02', entry_price='100.02',
                    stressed_exit_price='98', stop_price='99')
    assert 'stop_not_already_breached' in result['failed_checks']
    assert result['stressed_loss_cash'] == '8.54'


def test_stressed_equity_cannot_fund_oversized_cash_position():
    r = review(quantity='10', max_quantity='20', max_position_loss_cash='50',
               existing_notional_cash='0', existing_margin_cash='0', equity_cash='1000')
    assert 'stressed_equity_margin' in r['failed_checks']
    assert 'stressed_equity_leverage' in r['failed_checks']
    assert 'cash_funded' in r['failed_checks']


def test_digest_binds_grid_contract_identity_and_clock_without_authorizing():
    a = candidate()
    before = deepcopy(a)
    first = evaluate_contract_order(a, now_ms=NOW)
    assert a == before
    assert first == evaluate_contract_order(a, now_ms=NOW)
    assert first['review_sha256'] == evaluate_contract_order(candidate(quantity='2.0'), now_ms=NOW)['review_sha256']
    for change in ({'price_tick':'0.001'}, {'contract_id':'test-spec-v2'},
                   {'client_order_id':'order-2'}, {'quote_id':'q-2'},
                   {'contract_spec_observed_at_ms':NOW-10001}):
        assert first['review_sha256'] != review(**change)['review_sha256']
    assert first['review_sha256'] != evaluate_contract_order(a, now_ms=NOW+1)['review_sha256']


def test_declared_unrealized_profit_does_not_expand_daily_budget():
    assert review(daily_unrealized_pnl_cash='9999')['stressed_equity_cash'] == review(daily_unrealized_pnl_cash='0')['stressed_equity_cash']


def test_cash_selling_not_silently_reinterpreted_as_short():
    r = review(direction='SELL', entry_price='100', stop_price='101', stressed_exit_price='102')
    assert 'cash_account_buy_only' in r['failed_checks']
    assert r['may_execute_real_order'] is False
