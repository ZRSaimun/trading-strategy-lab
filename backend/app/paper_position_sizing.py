"""Disconnected, fail-closed Decimal sizing for hypothetical PAPER positions.

No broker access, order submission, durable reservation, or approval authority.
All amounts and price inputs are owner-declared and in one account currency.
"""
from decimal import Decimal, ROUND_FLOOR, localcontext
import re

_UNSIGNED = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_SIGNED = re.compile(r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")


def _number(value, name, *, positive=False, signed=False):
    if not isinstance(value, str) or not (_SIGNED if signed else _UNSIGNED).fullmatch(value):
        raise ValueError(f"Invalid decimal string: {name}")
    result = Decimal(value)
    if positive and result <= 0:
        raise ValueError(f"Must be positive: {name}")
    return result


def size_paper_position(*, side, account_equity_cash, max_position_loss_cash,
                        max_daily_loss_cash, daily_realized_pnl_cash,
                        daily_unrealized_pnl_cash, other_reserved_loss_cash,
                        entry_price, stop_price, stressed_exit_price,
                        point_value_cash, estimated_fixed_cost_cash,
                        quantity_step, minimum_quantity, maximum_quantity,
                        max_leverage, margin_requirement_percent,
                        other_gross_notional_cash, other_reserved_margin_cash,
                        account_mode="MARGIN_SIMULATION"):
    """Return a non-executable, floor-rounded size or zero with explicit blockers.

    estimated_fixed_cost_cash is a fixed total scenario cost, not a per-unit
    commission; callers must conservatively bound variable costs separately.
    The stressed exit must be beyond the stop in the loss direction.
    """
    if side not in ("BUY", "SELL") or account_mode not in ("CASH", "MARGIN_SIMULATION"):
        raise ValueError("Invalid side or account mode")
    with localcontext() as ctx:
        ctx.prec = 64
        values = {}
        for name, value, positive, signed in (
            ("account_equity_cash", account_equity_cash, True, False),
            ("max_position_loss_cash", max_position_loss_cash, True, False),
            ("max_daily_loss_cash", max_daily_loss_cash, True, False),
            ("daily_realized_pnl_cash", daily_realized_pnl_cash, False, True),
            ("daily_unrealized_pnl_cash", daily_unrealized_pnl_cash, False, True),
            ("other_reserved_loss_cash", other_reserved_loss_cash, False, False),
            ("entry_price", entry_price, True, False),
            ("stop_price", stop_price, True, False),
            ("stressed_exit_price", stressed_exit_price, True, False),
            ("point_value_cash", point_value_cash, True, False),
            ("estimated_fixed_cost_cash", estimated_fixed_cost_cash, False, False),
            ("quantity_step", quantity_step, True, False),
            ("minimum_quantity", minimum_quantity, True, False),
            ("maximum_quantity", maximum_quantity, True, False),
            ("max_leverage", max_leverage, True, False),
            ("margin_requirement_percent", margin_requirement_percent, True, False),
            ("other_gross_notional_cash", other_gross_notional_cash, False, False),
            ("other_reserved_margin_cash", other_reserved_margin_cash, False, False),
        ):
            values[name] = _number(value, name, positive=positive, signed=signed)
        v = values
        if v["margin_requirement_percent"] > 100 or v["max_leverage"] > 100:
            raise ValueError("Margin percentage or leverage outside supported range")
        if (side == "BUY" and not (v["stressed_exit_price"] < v["stop_price"] < v["entry_price"])) or (
            side == "SELL" and not (v["entry_price"] < v["stop_price"] < v["stressed_exit_price"])
        ):
            raise ValueError("Protective stop/stress exit on wrong side of entry")
        if account_mode == "CASH" and side == "SELL":
            raise ValueError("Cash-mode SELL represents an unsupported new short entry")
        if account_mode == "CASH" and (v["max_leverage"] != 1 or v["margin_requirement_percent"] != 100):
            raise ValueError("Cash mode requires 1x leverage and 100% funding")

        downside = (v["daily_realized_pnl_cash"]
                    + min(v["daily_unrealized_pnl_cash"], Decimal(0))
                    - v["other_reserved_loss_cash"])
        daily_remaining = v["max_daily_loss_cash"] + downside
        cash_budget = min(v["max_position_loss_cash"], v["account_equity_cash"],
                          v["max_daily_loss_cash"], daily_remaining)
        per_unit_stress = abs(v["entry_price"] - v["stressed_exit_price"]) * v["point_value_cash"]
        per_unit_notional = v["entry_price"] * v["point_value_cash"]
        per_unit_margin = per_unit_notional * v["margin_requirement_percent"] / Decimal(100)
        free_gross_notional = v["account_equity_cash"] * v["max_leverage"] - v["other_gross_notional_cash"]
        free_margin = v["account_equity_cash"] - v["other_reserved_margin_cash"]
        blockers = []
        if cash_budget <= v["estimated_fixed_cost_cash"]:
            blockers.append("loss_budget_exhausted")
        if free_gross_notional <= 0:
            blockers.append("gross_leverage_exhausted")
        if free_margin <= 0:
            blockers.append("margin_exhausted")
        if blockers:
            quantity = Decimal(0)
        else:
            raw_max = min(
                (cash_budget - v["estimated_fixed_cost_cash"]) / per_unit_stress,
                free_gross_notional / per_unit_notional,
                free_margin / per_unit_margin,
                v["maximum_quantity"],
            )
            quantity = (raw_max / v["quantity_step"]).to_integral_value(rounding=ROUND_FLOOR) * v["quantity_step"]
            if quantity < v["minimum_quantity"]:
                blockers.append("minimum_lot_exceeds_limits")
                quantity = Decimal(0)
        loss = per_unit_stress * quantity + (v["estimated_fixed_cost_cash"] if quantity > 0 else Decimal(0))
        notional = per_unit_notional * quantity
        margin = per_unit_margin * quantity
        # Recheck after floor quantization; no upward rounding is ever allowed.
        if quantity > 0 and not (
            loss <= cash_budget and notional <= free_gross_notional
            and margin <= free_margin and quantity <= v["maximum_quantity"]
        ):
            raise ArithmeticError("Sizing invariant violated; do not place an order")
        return {
            "illustrative_constraints_satisfied": quantity > 0,
            "quantity": str(quantity),
            "stressed_loss_cash": str(loss),
            "gross_notional_cash": str(notional),
            "margin_cash": str(margin),
            "available_stressed_loss_budget_cash": str(max(Decimal(0), cash_budget)),
            "daily_loss_headroom_cash": str(max(Decimal(0), daily_remaining)),
            "failed_checks": blockers,
            "broker_quote_verified": False,
            "broker_balance_verified": False,
            "durable_risk_reservation": False,
            "human_order_confirmation_verified": False,
            "may_execute_paper_order": False,
            "may_execute_real_order": False,
            "warnings": [
                "Owner-declared inputs only; this is not broker buying power or an executable quote.",
                "Stressed exits, costs and stop losses cannot cap real gap or liquidation losses.",
                "Fixed cost must bound all quantity-dependent commissions/slippage externally.",
                "No broker execution, durable reservation or human order approval exists here.",
            ],
        }
