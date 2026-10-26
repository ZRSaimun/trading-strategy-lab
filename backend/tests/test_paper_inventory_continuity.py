"""Synthetic-only risk inventory continuity regressions."""
from copy import deepcopy
import pytest

from app.paper_inventory_continuity import audit_paper_inventory_continuity as audit

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


def pair():
    before = snapshot()
    after = deepcopy(before)
    after['exposures'][0]['quote_observed_at_ms'] = NOW + 500
    after['exposures'][0]['quote_received_at_ms'] = NOW + 600
    return before, after


def run(before, after, delta=1000):
    return audit(before, after, previous_now_ms=NOW, now_ms=NOW+delta)


def test_stable_inventory_with_fresh_quotes_never_authorizes_orders():
    before, after = pair()
    result = run(before, after)
    assert result['status'] == 'CONTINUITY_ONLY_UNVERIFIED'
    assert result['failed_checks'] == []
    assert result['broker_authenticated'] is False
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False
    assert len(result['diagnostic_sha256']) == 64
    assert run(before, after)['diagnostic_sha256'] == result['diagnostic_sha256']


@pytest.mark.parametrize('mutation,check', [
    (lambda p: p['exposures'].clear(), 'no_unverified_order_disappearance'),
    (lambda p: p['exposures'].append(dict(p['exposures'][0], client_order_id='paper-order-0002')), 'no_unreserved_order_addition'),
    (lambda p: p['exposures'][0].update(state='OPEN'), 'order_state_unchanged_without_broker_receipt'),
    (lambda p: p['exposures'][0].update(state='CANCEL_REQUESTED'), 'order_state_unchanged_without_broker_receipt'),
    (lambda p: p['exposures'][0].update(quantity='2'), 'order_risk_terms_unchanged'),
    (lambda p: p['exposures'][0].update(stop_price='1981'), 'order_risk_terms_unchanged'),
    (lambda p: p['exposures'][0].update(provider='OTHER'), 'order_risk_terms_unchanged'),
    (lambda p: p.update(account_id='another-acct-001'), 'account_identity_unchanged'),
    (lambda p: p.update(max_gross_leverage='3'), 'risk_policy_unchanged'),
    (lambda p: p.update(equity_cash='11000'), 'cash_and_realized_pnl_unchanged'),
    (lambda p: p.update(daily_realized_pnl_cash='0'), 'cash_and_realized_pnl_unchanged'),
    (lambda p: p.update(daily_unrealized_pnl_cash='1000'), 'cash_and_realized_pnl_unchanged'),
])
def test_changed_declared_inventory_requires_reconciliation(mutation, check):
    before, after = pair()
    mutation(after)
    result = run(before, after)
    assert check in result['failed_checks']
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert result['may_execute_real_order'] is False


def test_replayed_quote_does_not_refresh_inventory():
    before, after = pair()
    after['exposures'][0]['quote_observed_at_ms'] = before['exposures'][0]['quote_observed_at_ms']
    assert 'quote_clocks_advanced' in run(before, after)['failed_checks']


def test_emergency_latch_cannot_be_silently_cleared():
    before, after = pair()
    before['emergency_latched'] = True
    result = run(before, after)
    assert 'emergency_latch_not_cleared' in result['failed_checks']
    assert 'previous_risk_within_declared_limits' in result['failed_checks']


def test_current_breached_stop_blocks_even_if_inventory_unchanged():
    before, after = pair()
    after['exposures'][0].update(bid='1979', ask='1980')
    assert 'current_risk_within_declared_limits' in run(before, after)['failed_checks']


def test_long_observation_gap_requires_hold():
    before, after = pair()
    assert 'observation_interval_within_60s' in run(before, after, delta=61_000)['failed_checks']


@pytest.mark.parametrize('previous_time,current_time', [(NOW, NOW), (NOW+1, NOW), (True, NOW+1)])
def test_invalid_clock_order_fails_closed(previous_time, current_time):
    before, after = pair()
    with pytest.raises(ValueError):
        audit(before, after, previous_now_ms=previous_time, now_ms=current_time)


def test_unknown_fields_rejected_without_secret_leak():
    before, after = pair()
    after['broker_api_token'] = 'do-not-store'
    with pytest.raises(ValueError):
        run(before, after)
