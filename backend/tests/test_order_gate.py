"""Synthetic risk-gate preview tests: no external quotes, state or broker calls."""
import pytest
from pydantic import ValidationError
from app.order_gate import OrderGateContext, evaluate_gate

NOW = 1_790_000_000_000


def context(**changes):
    payload = dict(
        quote=dict(instrument='XAUUSD', provider='TEST-QUOTE', venue='TEST-OTC',
                   bid=100.0, ask=100.02, observed_at_ms=NOW-500, received_at_ms=NOW-400),
        expected_instrument='XAUUSD', expected_provider='TEST-QUOTE', expected_venue='TEST-OTC',
        max_quote_age_ms=1000, max_transport_lag_ms=500, max_spread_bps=5,
        client_order_id='order-123456', prior_client_order_ids=[],
        existing_open_or_pending_order=False, kill_switch_active=False,
        market_session_open=True, daily_realized_pnl_cash=-10,
        max_daily_loss_cash=50, consecutive_losses=0, max_consecutive_losses=3,
        owner_confirmed_this_order=True,
    )
    payload.update(changes)
    return OrderGateContext(**payload)


def quote(**changes):
    return dict(context().quote.model_dump(), **changes)


def test_hypothetical_pass_never_authorizes_orders():
    result = evaluate_gate(context(), NOW)
    assert result['assumption_checks_pass']
    assert result['failed_checks'] == []
    assert result['quote_authenticated'] is False
    assert result['durable_order_reservation'] is False
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False


@pytest.mark.parametrize('changes,expected', [
    (dict(quote=quote(observed_at_ms=NOW-1500)), 'quote_fresh'),
    (dict(quote=quote(received_at_ms=NOW+1)), 'timestamp_order'),
    (dict(quote=quote(received_at_ms=NOW-10, observed_at_ms=NOW-1000),
                max_transport_lag_ms=500), 'transport_lag_acceptable'),
    (dict(quote=quote(provider='UNKNOWN')), 'exact_source_identity'),
    (dict(quote=quote(venue='OTHER')), 'exact_source_identity'),
    (dict(quote=quote(instrument='NQ')), 'exact_source_identity'),
    (dict(quote=quote(ask=99.99)), 'valid_bid_ask'),
    (dict(quote=quote(ask=100.5)), 'spread_within_limit'),
    (dict(prior_client_order_ids=['order-123456']), 'new_client_order_id'),
    (dict(existing_open_or_pending_order=True), 'no_existing_order'),
    (dict(kill_switch_active=True), 'kill_switch_off'),
    (dict(market_session_open=False), 'session_open'),
    (dict(daily_realized_pnl_cash=-50), 'daily_loss_limit_not_reached'),
    (dict(consecutive_losses=3), 'loss_streak_limit_not_reached'),
    (dict(owner_confirmed_this_order=False), 'specific_owner_confirmation'),
])
def test_each_blocker_fails_closed(changes, expected):
    result = evaluate_gate(context(**changes), NOW)
    assert expected in result['failed_checks']
    assert result['assumption_checks_pass'] is False
    assert result['may_execute_real_order'] is False


def test_quote_ratio_overflow_or_roundoff_cannot_approve_zero_spread():
    result = evaluate_gate(context(quote=quote(bid=1e-300, ask=1e300)), NOW)
    assert 'finite_spread' in result['failed_checks']
    assert result['spread_bps'] is None
    result = evaluate_gate(context(quote=quote(bid=1e200, ask=1e200+1e180)), NOW)
    assert result['assumption_checks_pass'] is False


def test_invalid_inputs_and_untrusted_clock_are_rejected():
    with pytest.raises(ValidationError):
        context(client_order_id='bad id')
    with pytest.raises(ValidationError):
        context(quote=quote(bid=float('nan')))
    assert 'timestamp_order' in evaluate_gate(context(), NOW-1000)['failed_checks']
    with pytest.raises(ValueError):
        evaluate_gate(context(), float(NOW))


def test_pure_replay_does_not_reserve_order_id():
    state = context()
    assert evaluate_gate(state, NOW) == evaluate_gate(state, NOW)
    assert state.prior_client_order_ids == []


def test_existing_unrealized_losses_and_reserved_downside_count_toward_daily_cap():
    # Realized P&L is within the cap, but exposure elsewhere in the account
    # already consumes more than the remaining loss budget.
    result = evaluate_gate(context(
        daily_realized_pnl_cash=-10,
        daily_unrealized_pnl_cash=-25,
        other_positions_reserved_stress_loss_cash=20,
    ), NOW)
    assert result['checks']['daily_loss_limit_not_reached'] is True
    assert result['checks']['existing_account_downside_within_cap'] is False
    assert result['effective_daily_pnl_after_existing_risk_cash'] == -55
    assert result['may_execute_real_order'] is False


def test_floating_profits_cannot_expand_the_loss_budget():
    result = evaluate_gate(context(
        daily_realized_pnl_cash=-40,
        daily_unrealized_pnl_cash=1000,
        other_positions_reserved_stress_loss_cash=15,
    ), NOW)
    assert result['effective_daily_pnl_after_existing_risk_cash'] == -55
    assert not result['checks']['existing_account_downside_within_cap']


def test_reserved_risk_rejects_negative_and_overflowing_aggregates():
    with pytest.raises(ValidationError):
        context(other_positions_reserved_stress_loss_cash=-1)
    result = evaluate_gate(context(
        daily_realized_pnl_cash=-1e308,
        other_positions_reserved_stress_loss_cash=1e308,
    ), NOW)
    assert result['effective_daily_pnl_after_existing_risk_cash'] is None
    assert not result['checks']['existing_account_downside_within_cap']
    assert not result['assumption_checks_pass']
