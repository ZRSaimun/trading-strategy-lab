"""Authenticated risk/quote gate endpoint: synthetic inputs, no broker calls."""
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.broker_readiness import build_router


def request(**changes):
    now = time.time_ns() // 1_000_000
    risk = dict(
        broker='Trading212-Invest', symbol='XAUUSD', direction='BUY',
        entry_price=100.03, stop_price=98, stressed_exit_price=96,
        quantity=2, point_value=1, estimated_total_cost=1,
        account_equity=1000, risk_budget_percent=2,
        margin_requirement_percent=10, max_leverage=2,
        price_source='UNVERIFIED USER INPUT',
    )
    controls = dict(
        quote=dict(instrument='XAUUSD', provider='DECLARED-TEST', venue='TEST',
                   bid=100, ask=100.02, observed_at_ms=now-500,
                   received_at_ms=now-400),
        expected_instrument='XAUUSD', expected_provider='DECLARED-TEST',
        expected_venue='TEST', client_order_id='test-order-001',
        prior_client_order_ids=[], kill_switch_active=False,
        market_session_open=True, daily_realized_pnl_cash=0,
        max_daily_loss_cash=50, owner_confirmed_this_order=True,
        max_quote_age_ms=2000, max_transport_lag_ms=1000, max_spread_bps=5,
    )
    body = {'risk': risk, 'controls': controls}
    body.update(changes)
    return body


def client(owner=lambda: 'owner'):
    app = FastAPI()
    app.include_router(build_router(owner))
    return TestClient(app)


def test_passing_preview_is_never_an_order_authorization():
    response = client().post('/api/broker/order-gate-preview', json=request())
    assert response.status_code == 200
    result = response.json()
    assert result['assumption_checks_pass'] is True
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False
    assert result['broker_connection_verified'] is False
    assert result['quote_authenticated'] is False
    assert result['durable_circuit_breaker'] is False
    assert result['hypothetical_risk']['all_hypothetical_limits_pass'] is True


def test_cfd_account_fails_documented_api_support_even_when_risk_passes():
    data = request()
    data['risk']['broker'] = 'Trading212-CFD'
    result = client().post('/api/broker/order-gate-preview', json=data).json()
    assert 'documented_account_api_support' in result['failed_checks']
    assert result['may_execute_real_order'] is False


def test_mismatched_or_optimistic_quote_fails_closed():
    data = request()
    data['controls']['quote']['instrument'] = 'NQ'
    result = client().post('/api/broker/order-gate-preview', json=data).json()
    assert 'instrument_matches_order' in result['failed_checks']
    data = request()
    data['risk']['entry_price'] = 100.01
    result = client().post('/api/broker/order-gate-preview', json=data).json()
    assert 'entry_not_optimistic_vs_quote' in result['failed_checks']


def test_stale_duplicate_kill_switch_and_failed_stress_are_not_approved():
    data = request()
    data['controls']['quote']['observed_at_ms'] -= 60_000
    data['controls']['prior_client_order_ids'] = ['test-order-001']
    data['controls']['kill_switch_active'] = True
    data['risk']['stressed_exit_price'] = 70
    result = client().post('/api/broker/order-gate-preview', json=data).json()
    assert {'quote_fresh','new_client_order_id','kill_switch_off',
            'hypothetical_stress_limits'} <= set(result['failed_checks'])
    assert result['may_execute_real_order'] is False


def test_endpoint_authentication_and_no_order_route():
    def deny():
        raise HTTPException(401, 'Authentication required')
    assert client(deny).post('/api/broker/order-gate-preview', json=request()).status_code == 401
    assert client().post('/api/broker/order', json=request()).status_code == 404


def test_proposed_stress_loss_must_not_break_daily_loss_cap():
    data = request()
    # Current realised loss is below 50, but another 9.06 of stressed
    # hypothetical loss would breach the chosen 50-unit daily limit.
    data['controls']['daily_realized_pnl_cash'] = -45
    result = client().post('/api/broker/order-gate-preview', json=data).json()
    assert result['checks']['daily_loss_limit_not_reached'] is True
    assert result['checks']['projected_daily_loss_within_cap'] is False
    assert result['may_execute_real_order'] is False


def test_account_wide_existing_downside_blocks_proposed_order():
    data = request()
    data['controls'].update(
        daily_realized_pnl_cash=-10,
        daily_unrealized_pnl_cash=-25,
        other_positions_reserved_stress_loss_cash=10,
    )
    response = client().post('/api/broker/order-gate-preview', json=data)
    assert response.status_code == 200
    result = response.json()
    assert result['checks']['daily_loss_limit_not_reached'] is True
    assert result['checks']['existing_account_downside_within_cap'] is True
    # Existing account downside is 45. A further ~9.06 stressed loss
    # breaches the 50 daily cash limit.
    assert result['checks']['projected_daily_loss_within_cap'] is False
    scenario = result['account_wide_daily_loss_scenario']
    assert scenario['effective_pnl_before_proposed_order_cash'] == -45
    assert scenario['projected_pnl_after_proposed_stress_cash'] < -50
    assert result['may_execute_real_order'] is False


def test_floating_gains_cannot_offset_account_wide_risk_and_invalid_reserve_rejected():
    data = request()
    data['controls'].update(
        daily_realized_pnl_cash=-40,
        daily_unrealized_pnl_cash=1000,
        other_positions_reserved_stress_loss_cash=15,
    )
    result = client().post('/api/broker/order-gate-preview', json=data).json()
    assert result['account_wide_daily_loss_scenario']['unrealized_loss_cash'] == 0
    assert result['checks']['existing_account_downside_within_cap'] is False
    assert result['checks']['projected_daily_loss_within_cap'] is False
    data['controls']['other_positions_reserved_stress_loss_cash'] = -1
    assert client().post('/api/broker/order-gate-preview', json=data).status_code == 422
