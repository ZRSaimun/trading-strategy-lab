"""Stressed-equity preview regression tests; all inputs are synthetic and non-executing."""
import time

import pytest

from app.broker_readiness import (
    OrderGatePreview, StressPreview, calculate_order_gate_preview,
    calculate_stress_preview,
)


def risk(**changes):
    return dict(
        broker="Trading212-Invest", symbol="XAUUSD", direction="BUY",
        entry_price=100, stop_price=98, stressed_exit_price=97,
        quantity=19, point_value=1, estimated_total_cost=0,
        account_equity=1000, risk_budget_percent=10,
        margin_requirement_percent=10, max_leverage=2,
        price_source="UNVERIFIED USER INPUT",
    ) | changes


def gate(*, risk_changes=None, control_changes=None):
    now = time.time_ns() // 1_000_000
    body = {
        "risk": risk(entry_price=100.03, stop_price=98, stressed_exit_price=96,
                     quantity=2, estimated_total_cost=1,
                     **(risk_changes or {})),
        "controls": dict(
            quote=dict(instrument="XAUUSD", provider="DECLARED-TEST", venue="TEST",
                       bid=100, ask=100.02, observed_at_ms=now-500,
                       received_at_ms=now-400),
            expected_instrument="XAUUSD", expected_provider="DECLARED-TEST",
            expected_venue="TEST", client_order_id="stress-preview-0001",
            prior_client_order_ids=[], kill_switch_active=False,
            market_session_open=True, daily_realized_pnl_cash=0,
            max_daily_loss_cash=50, max_position_loss_cash=15,
            owner_confirmed_this_order=True, max_quote_age_ms=2000,
            max_transport_lag_ms=1000, max_spread_bps=5,
        ) | (control_changes or {}),
    }
    return calculate_order_gate_preview(OrderGatePreview(**body), now)


def test_stressed_leverage_fails_when_initial_leverage_passes():
    result = calculate_stress_preview(StressPreview(**risk()))
    assert result["assumed_effective_leverage"] == pytest.approx(1.9)
    assert result["stressed_loss_within_budget"]
    assert result["assumed_margin_covered_by_equity"]
    assert result["assumed_stressed_effective_leverage"] > 2
    assert not result["within_user_leverage_cap"]
    assert not result["all_hypothetical_limits_pass"]
    assert result["may_execute_real_order"] is False


def test_stressed_margin_fails_when_initial_equity_covers_margin():
    result = calculate_stress_preview(StressPreview(**risk(
        quantity=9.5, stop_price=99, stressed_exit_price=90,
        margin_requirement_percent=100, max_leverage=10,
    )))
    assert result["assumed_margin_required"] == 950
    assert result["stressed_equity_remaining_cash"] == 905
    assert not result["assumed_margin_covered_by_equity"]
    assert result["within_user_leverage_cap"]
    assert not result["all_hypothetical_limits_pass"]


def test_exhausted_stressed_equity_never_passes_or_returns_infinite_leverage():
    result = calculate_stress_preview(StressPreview(**risk(
        quantity=2, account_equity=100, risk_budget_percent=100,
        stressed_exit_price=1, max_leverage=10,
    )))
    assert result["stressed_equity_remaining_cash"] == -98
    assert result["stressed_equity_positive"] is False
    assert result["assumed_stressed_effective_leverage"] is None
    assert not result["all_hypothetical_limits_pass"]
    assert result["may_execute_paper_order"] is False


def test_rounded_away_stress_loss_fails_closed():
    result = calculate_stress_preview(StressPreview(**risk(
        quantity=1, account_equity=1e300, max_leverage=100,
        risk_budget_percent=100,
    )))
    assert result["stressed_equity_remaining_cash"] == 1e300
    assert result["stressed_equity_positive"] is False
    assert not result["all_hypothetical_limits_pass"]


def test_portfolio_leverage_uses_stressed_equity_not_initial_equity():
    result = gate(control_changes={"other_positions_gross_notional_cash": 1785})
    assert result["checks"]["hypothetical_stress_limits"]
    assert result["portfolio_exposure_scenario"]["combined_gross_notional_cash"] < 2000
    assert result["portfolio_exposure_scenario"]["combined_gross_leverage"] > 2
    assert not result["checks"]["portfolio_gross_leverage_within_cap"]
    assert result["may_execute_real_order"] is False


def test_portfolio_margin_uses_stressed_equity_not_initial_equity():
    result = gate(control_changes={"other_positions_reserved_margin_cash": 971})
    scenario = result["portfolio_exposure_scenario"]
    assert scenario["combined_margin_cash"] < 1000
    assert scenario["combined_margin_cash"] > scenario["remaining_stressed_equity_cash"]
    assert not result["checks"]["portfolio_margin_within_equity"]


def test_other_reserved_downside_reduces_portfolio_stressed_equity():
    result = gate(control_changes={
        "other_positions_gross_notional_cash": 1760,
        "other_positions_reserved_stress_loss_cash": 20,
    })
    assert result["checks"]["projected_daily_loss_within_cap"]
    assert result["portfolio_exposure_scenario"]["remaining_stressed_equity_cash"] < 980
    assert not result["checks"]["portfolio_gross_leverage_within_cap"]


def test_cash_account_funding_uses_stressed_equity():
    result = gate(control_changes={"other_positions_gross_notional_cash": 794.9})
    assert result["checks"]["portfolio_gross_leverage_within_cap"]
    assert result["portfolio_exposure_scenario"]["combined_gross_notional_cash"] < 1000
    assert not result["checks"]["cash_account_gross_fully_funded"]
    assert result["may_execute_real_order"] is False


def test_exhausted_portfolio_stressed_equity_has_no_nan_json_values():
    result = gate(control_changes={
        "other_positions_reserved_stress_loss_cash": 999,
    })
    assert not result["checks"]["portfolio_stressed_equity_positive"]
    assert not result["checks"]["portfolio_margin_within_equity"]
    assert not result["checks"]["portfolio_gross_leverage_within_cap"]
    assert result["portfolio_exposure_scenario"]["combined_gross_leverage"] is None
    assert result["may_execute_paper_order"] is False
