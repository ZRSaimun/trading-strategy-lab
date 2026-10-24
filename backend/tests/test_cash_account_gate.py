"""Synthetic cash-account safeguards; these previews never place orders.

Official references checked 24 Oct 2026:
https://docs.trading212.com/api
https://helpcentre.trading212.com/hc/en-us/articles/360009036118-What-are-the-differences-between-CFD-and-Invest
"""
import time

from app.broker_readiness import OrderGatePreview, calculate_order_gate_preview


def payload(*, broker='Trading212-Invest', direction='BUY', other_gross=0):
    now = time.time_ns() // 1_000_000
    risk = {
        'broker': broker, 'symbol': 'XAUUSD', 'direction': direction,
        'entry_price': 100.03 if direction == 'BUY' else 99.97,
        'stop_price': 98 if direction == 'BUY' else 102,
        'stressed_exit_price': 96 if direction == 'BUY' else 104,
        'quantity': 2, 'point_value': 1, 'estimated_total_cost': 1,
        'account_equity': 1000, 'risk_budget_percent': 2,
        'margin_requirement_percent': 10, 'max_leverage': 2,
        'price_source': 'UNVERIFIED USER INPUT',
    }
    controls = {
        'quote': {
            'instrument': 'XAUUSD', 'provider': 'DECLARED-TEST',
            'venue': 'TEST', 'bid': 100, 'ask': 100.02,
            'observed_at_ms': now - 500, 'received_at_ms': now - 400,
        },
        'expected_instrument': 'XAUUSD',
        'expected_provider': 'DECLARED-TEST',
        'expected_venue': 'TEST',
        'client_order_id': 'cash-gate-123456',
        'kill_switch_active': False,
        'market_session_open': True,
        'max_daily_loss_cash': 50,
        'owner_confirmed_this_order': True,
        'max_quote_age_ms': 2000,
        'max_transport_lag_ms': 1000,
        'max_spread_bps': 5,
        'other_positions_gross_notional_cash': other_gross,
    }
    return OrderGatePreview(risk=risk, controls=controls), now


def test_fully_funded_cash_buy_remains_hypothetically_valid_only():
    body, now = payload()
    result = calculate_order_gate_preview(body, now)
    assert result['checks']['cash_account_no_short_entry']
    assert result['checks']['cash_account_gross_fully_funded']
    assert result['assumption_checks_pass']
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False


def test_cash_account_short_entry_rejected_despite_other_checks_passing():
    for broker in ('Trading212-Invest', 'Trading212-StocksISA'):
        body, now = payload(broker=broker, direction='SELL')
        result = calculate_order_gate_preview(body, now)
        assert result['checks']['hypothetical_stress_limits']
        assert result['checks']['entry_not_optimistic_vs_quote']
        assert not result['checks']['cash_account_no_short_entry']
        assert 'cash_account_no_short_entry' in result['failed_checks']
        assert not result['assumption_checks_pass']
        assert not result['may_execute_real_order']


def test_cash_account_cannot_borrow_even_if_user_cap_allows_two_x():
    for broker in ('Trading212-Invest', 'Trading212-StocksISA'):
        body, now = payload(broker=broker, other_gross=900)
        result = calculate_order_gate_preview(body, now)
        assert result['checks']['portfolio_gross_leverage_within_cap']
        assert result['checks']['portfolio_margin_within_equity']
        assert not result['checks']['cash_account_gross_fully_funded']
        assert 'cash_account_gross_fully_funded' in result['failed_checks']
        assert not result['assumption_checks_pass']


def test_cfd_public_api_remains_unsupported_without_cash_only_misclassification():
    body, now = payload(broker='Trading212-CFD')
    result = calculate_order_gate_preview(body, now)
    assert not result['checks']['documented_account_api_support']
    assert result['checks']['cash_account_no_short_entry']
    assert result['checks']['cash_account_gross_fully_funded']
    assert not result['may_execute_real_order']
