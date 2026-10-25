"""Synthetic read-only group concentration checks; never uses brokerage data."""
from copy import deepcopy
import pytest

from app.paper_group_concentration_guard import evaluate_grouped_paper_exposure

NOW = 1_800_000_000_000


def snapshot():
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


def policy():
    return {
        'instrument_groups': {'XAUUSD': 'GOLD'},
        'group_notional_caps_cash': {'GOLD': '5000'},
        'max_group_share_of_stressed_equity': '0.5',
    }


def run(s=None, p=None):
    return evaluate_grouped_paper_exposure(s if s is not None else snapshot(),
                                           p if p is not None else policy(), now_ms=NOW)


def test_nominal_preview_remains_disconnected_and_unverified():
    result = run()
    assert result['status'] == 'ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED'
    assert result['declared_group_notional_cash'] == {'GOLD': '2002'}
    assert result['group_mapping_authenticated'] is False
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False


def test_two_aliases_same_group_fail_while_individual_symbols_pass():
    s = snapshot()
    other = deepcopy(s['exposures'][0]); other['client_order_id'] = 'paper-order-0002'
    other['instrument'] = 'GOLD-CFD'
    s['exposures'].append(other)
    p = policy(); p['instrument_groups']['GOLD-CFD'] = 'GOLD'
    p['group_notional_caps_cash']['GOLD'] = '3000'
    result = run(s, p)
    assert result['checks']['symbol_notional_within_cap'] is True
    assert result['checks']['declared_group_notional_within_cap'] is False
    assert result['declared_group_notional_cash']['GOLD'] == '4004'
    assert result['status'] == 'HOLD_RECONCILIATION'


def test_stressed_equity_group_share_fails_even_when_nominal_group_cap_passes():
    p = policy(); p['max_group_share_of_stressed_equity'] = '0.2'
    result = run(p=p)
    assert result['checks']['declared_group_notional_within_cap'] is True
    assert result['checks']['declared_group_stressed_equity_share_within_cap'] is False
    assert result['status'] == 'HOLD_RECONCILIATION'


def test_base_guard_hold_is_never_overridden_by_group_pass():
    s = snapshot(); s['emergency_latched'] = True
    result = run(s=s)
    assert 'emergency_latch_clear' in result['failed_checks']
    assert result['checks']['declared_group_notional_within_cap'] is True
    assert result['may_execute_real_order'] is False


def test_missing_mapping_rejected_instead_of_ignoring_position():
    p = policy(); p['instrument_groups'] = {}
    with pytest.raises(ValueError, match='Every instrument'):
        run(p=p)


def test_extra_mapping_and_missing_group_cap_rejected():
    p = policy(); p['instrument_groups']['XAGUSD'] = 'SILVER'
    with pytest.raises(ValueError): run(p=p)
    p = policy(); p['group_notional_caps_cash'] = {}
    with pytest.raises(ValueError, match='Every declared group'):
        run(p=p)


@pytest.mark.parametrize('invalid', ['0', '1.1', 'NaN', '1e-2', '-1', 0.2, '0.123456789'])
def test_invalid_group_fraction_rejected(invalid):
    p = policy(); p['max_group_share_of_stressed_equity'] = invalid
    with pytest.raises(ValueError): run(p=p)


def test_secret_like_unknown_fields_rejected():
    p = policy(); p['api_key'] = 'never'
    with pytest.raises(ValueError): run(p=p)


def test_empty_portfolio_never_claims_authenticated_inventory():
    s = snapshot(); s['exposures'] = []
    p = {'instrument_groups': {}, 'group_notional_caps_cash': {},
         'max_group_share_of_stressed_equity': '0.5'}
    out = run(s, p)
    assert out['declared_group_notional_cash'] == {}
    assert out['complete_open_order_inventory_verified'] is False
    assert out['may_execute_paper_order'] is False


def test_caller_inputs_unchanged():
    s = snapshot(); p = policy()
    old_s, old_p = deepcopy(s), deepcopy(p)
    run(s, p)
    assert s == old_s and p == old_p


def test_large_bounded_group_cap_and_precise_decimal():
    p = policy(); p['group_notional_caps_cash']['GOLD'] = '2002.00000001'
    assert run(p=p)['checks']['declared_group_notional_within_cap']
    p['group_notional_caps_cash']['GOLD'] = '2001.99999999'
    assert not run(p=p)['checks']['declared_group_notional_within_cap']
