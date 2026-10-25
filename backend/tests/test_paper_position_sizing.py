"""Offline, synthetic money-management tests; no broker or database."""
from decimal import Decimal
import pytest
from app.paper_position_sizing import size_paper_position


def sample(**changes):
    data = dict(side="BUY", account_equity_cash="1000", max_position_loss_cash="30",
                max_daily_loss_cash="50", daily_realized_pnl_cash="-10",
                daily_unrealized_pnl_cash="-5", other_reserved_loss_cash="5",
                entry_price="100", stop_price="99", stressed_exit_price="98",
                point_value_cash="1", estimated_fixed_cost_cash="2",
                quantity_step="0.1", minimum_quantity="0.1", maximum_quantity="100",
                max_leverage="2", margin_requirement_percent="50",
                other_gross_notional_cash="0", other_reserved_margin_cash="0")
    data.update(changes)
    return size_paper_position(**data)


def test_loss_limit_floors_not_rounds_up():
    result = sample()
    assert result["quantity"] == "14"
    assert result["stressed_loss_cash"] == "30"
    assert result["illustrative_constraints_satisfied"]
    assert not result["may_execute_real_order"] and not result["may_execute_paper_order"]


def test_existing_loss_and_reservation_reduce_daily_capacity():
    result = sample(daily_realized_pnl_cash="-35", daily_unrealized_pnl_cash="-5",
                    other_reserved_loss_cash="5")
    assert result["quantity"] == "1.5"
    assert result["daily_loss_headroom_cash"] == "5"


def test_floating_profit_cannot_offset_loss():
    assert sample(daily_unrealized_pnl_cash="1000")["quantity"] == "14"


def test_existing_margin_and_leverage_bound_quantity():
    assert sample(other_reserved_margin_cash="950")["quantity"] == "0.8"
    assert sample(other_gross_notional_cash="1900")["quantity"] == "0.8"
    assert sample(other_reserved_margin_cash="1000")["failed_checks"] == ["margin_exhausted"]


def test_minimum_lot_fails_closed():
    result = sample(minimum_quantity="15")
    assert result["quantity"] == "0"
    assert result["failed_checks"] == ["minimum_lot_exceeds_limits"]
    assert not result["illustrative_constraints_satisfied"]


def test_cash_mode_requires_full_funding_and_buy_only():
    result = sample(account_mode="CASH", max_leverage="1", margin_requirement_percent="100")
    assert result["quantity"] == "9.7"
    with pytest.raises(ValueError, match="short"):
        sample(account_mode="CASH", side="SELL", stop_price="101", stressed_exit_price="102",
               max_leverage="1", margin_requirement_percent="100")
    with pytest.raises(ValueError, match="Cash mode"):
        sample(account_mode="CASH")


def test_sell_stress_direction_and_sizing():
    result = sample(side="SELL", stop_price="101", stressed_exit_price="102")
    assert result["quantity"] == "14"
    with pytest.raises(ValueError, match="wrong side"):
        sample(side="SELL")


@pytest.mark.parametrize("changes", [
    {"entry_price": "NaN"}, {"quantity_step": "0"}, {"account_equity_cash": "-1"},
    {"max_position_loss_cash": "1e3"}, {"max_daily_loss_cash": 50},
    {"max_leverage": "101"}, {"margin_requirement_percent": "0"},
    {"stressed_exit_price": "100"}, {"other_reserved_loss_cash": "-1"},
    {"entry_price": "9999999999999"},
])
def test_invalid_inputs_rejected(changes):
    with pytest.raises(ValueError):
        sample(**changes)


def test_exhausted_daily_budget_and_fixed_cost_fail_closed():
    result = sample(daily_realized_pnl_cash="-50")
    assert result["quantity"] == "0"
    assert "loss_budget_exhausted" in result["failed_checks"]
    result = sample(estimated_fixed_cost_cash="30")
    assert result["quantity"] == "0"


def test_fractional_micro_lot_precision():
    result = sample(quantity_step="0.00000001", minimum_quantity="0.00000001",
                    max_position_loss_cash="0.00000005", estimated_fixed_cost_cash="0")
    assert result["quantity"] == "2E-8"
    assert result["stressed_loss_cash"] == "4E-8"


def test_maximum_quantity_and_no_broker_claim():
    result = sample(maximum_quantity="3.2")
    assert result["quantity"] == "3.2"
    assert not result["broker_quote_verified"]
    assert not result["human_order_confirmation_verified"]


def test_stressed_equity_is_debited_before_leverage_sizing():
    result = sample(other_gross_notional_cash="1900")
    q = Decimal(result["quantity"])
    stressed_equity = Decimal(result["stressed_equity_after_loss_cash"])
    assert q == Decimal("0.8")
    assert stressed_equity == Decimal("991.4")
    assert Decimal("1900") + q * 100 <= stressed_equity * 2
    # The next 0.1 lot passes current-equity leverage, but fails stressed leverage.
    assert Decimal("1900") + Decimal("0.9") * 100 > (
        Decimal("1000") - Decimal("5") - Decimal("2") - Decimal("0.9") * 2
    ) * 2
    assert result["may_execute_paper_order"] is False


def test_stressed_equity_is_debited_before_margin_sizing():
    result = sample(other_reserved_margin_cash="950")
    q = Decimal(result["quantity"])
    stressed_equity = Decimal(result["stressed_equity_after_loss_cash"])
    assert q == Decimal("0.8")
    assert Decimal("950") + q * 50 <= stressed_equity
    assert Decimal("950") + Decimal("0.9") * 50 > (
        Decimal("1000") - Decimal("5") - Decimal("2") - Decimal("0.9") * 2
    )


def test_declared_existing_risk_can_exhaust_stressed_equity():
    result = sample(other_reserved_loss_cash="999",
                    max_daily_loss_cash="2000", max_position_loss_cash="1000",
                    daily_realized_pnl_cash="0", daily_unrealized_pnl_cash="0")
    assert result["quantity"] == "0"
    assert "stressed_equity_exhausted" in result["failed_checks"]
    assert not result["illustrative_constraints_satisfied"]


def test_minimum_lot_refused_when_stressed_equity_cannot_cover_it():
    result = sample(other_reserved_loss_cash="990", max_daily_loss_cash="2000",
                    max_position_loss_cash="1000", daily_realized_pnl_cash="0",
                    daily_unrealized_pnl_cash="0", minimum_quantity="0.2")
    assert result["quantity"] == "0"
    assert result["failed_checks"] == ["minimum_lot_exceeds_limits"]


def test_short_side_and_floating_profit_cannot_bypass_stressed_leverage():
    result = sample(side="SELL", stop_price="101", stressed_exit_price="102",
                    other_gross_notional_cash="1900", daily_unrealized_pnl_cash="1000")
    assert result["quantity"] == "0.8"
    assert result["may_execute_real_order"] is False


def test_stressed_equity_result_includes_existing_and_new_downside():
    result = sample()
    assert result["stressed_equity_after_loss_cash"] == "965.0"
    assert result["stressed_loss_cash"] == "30"
