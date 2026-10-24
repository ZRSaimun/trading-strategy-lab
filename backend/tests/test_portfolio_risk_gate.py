"""Synthetic account-wide margin/gross-leverage gates; no broker side effects."""
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.broker_readiness import build_router


def request(**control_overrides):
    now = time.time_ns() // 1_000_000
    return {
        'risk': {
            'broker': 'Trading212-Invest', 'symbol': 'XAUUSD',
            'direction': 'BUY', 'entry_price': 100.03,
            'stop_price': 98, 'stressed_exit_price': 96,
            'quantity': 2, 'point_value': 1, 'estimated_total_cost': 1,
            'account_equity': 1000, 'risk_budget_percent': 2,
            'margin_requirement_percent': 10, 'max_leverage': 2,
            'price_source': 'UNVERIFIED USER INPUT',
        },
        'controls': {
            'quote': {
                'instrument': 'XAUUSD', 'provider': 'DECLARED-TEST',
                'venue': 'TEST', 'bid': 100, 'ask': 100.02,
                'observed_at_ms': now - 500,
                'received_at_ms': now - 400,
            },
            'expected_instrument': 'XAUUSD',
            'expected_provider': 'DECLARED-TEST',
            'expected_venue': 'TEST',
            'client_order_id': 'portfolio-123456',
            'kill_switch_active': False,
            'market_session_open': True,
            'max_daily_loss_cash': 50,
            'owner_confirmed_this_order': True,
            'max_quote_age_ms': 2000,
            'max_transport_lag_ms': 1000,
            'max_spread_bps': 5,
            **control_overrides,
        },
    }


def preview(data):
    app = FastAPI()
    app.include_router(build_router(lambda: 'owner'))
    return TestClient(app).post('/api/broker/order-gate-preview', json=data)


def test_baseline_passes_hypothetical_checks_but_never_authorizes_orders():
    result = preview(request()).json()
    assert result['assumption_checks_pass'] is True
    assert result['checks']['portfolio_margin_within_equity'] is True
    assert result['checks']['portfolio_gross_leverage_within_cap'] is True
    assert result['portfolio_exposure_scenario']['inputs_broker_verified'] is False
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False


def test_existing_reserved_margin_blocks_order_despite_own_margin_passing():
    result = preview(request(other_positions_reserved_margin_cash=990)).json()
    assert result['hypothetical_risk']['all_hypothetical_limits_pass'] is True
    assert result['checks']['portfolio_margin_within_equity'] is False
    assert result['checks']['portfolio_gross_leverage_within_cap'] is True
    assert result['portfolio_exposure_scenario']['combined_margin_cash'] > 1000
    assert not result['assumption_checks_pass']


def test_other_positions_gross_notional_blocks_aggregate_leverage():
    result = preview(request(other_positions_gross_notional_cash=1900)).json()
    assert result['hypothetical_risk']['all_hypothetical_limits_pass'] is True
    assert result['checks']['portfolio_margin_within_equity'] is True
    assert result['checks']['portfolio_gross_leverage_within_cap'] is False
    assert result['portfolio_exposure_scenario']['combined_gross_leverage'] > 2
    assert not result['assumption_checks_pass']


def test_portfolio_scenarios_pass_with_headroom_but_are_never_verified():
    result = preview(request(
        other_positions_reserved_margin_cash=100,
        other_positions_gross_notional_cash=500,
    )).json()
    assert result['assumption_checks_pass']
    assert result['portfolio_exposure_scenario']['combined_margin_cash'] > 100
    assert result['portfolio_exposure_scenario']['combined_gross_leverage'] < 2
    assert result['quote_authenticated'] is False
    assert result['broker_connection_verified'] is False


def test_negative_reservations_are_rejected_by_schema():
    for field in ('other_positions_reserved_margin_cash',
                  'other_positions_gross_notional_cash'):
        response = preview(request(**{field: -1}))
        assert response.status_code == 422


def test_precision_loss_in_existing_large_exposure_fails_closed():
    result = preview(request(
        other_positions_reserved_margin_cash=1e308,
        other_positions_gross_notional_cash=1e308,
    )).json()
    assert result['checks']['portfolio_margin_arithmetic_valid'] is False
    assert result['checks']['portfolio_gross_arithmetic_valid'] is False
    assert result['assumption_checks_pass'] is False
    assert result['may_execute_real_order'] is False
