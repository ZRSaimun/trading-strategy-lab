"""Owner-only execution capability inventory and zero-side-effect risk previews.

No broker requests, orders, key storage or mutable account access. The public
Trading 212 API covers Invest/Stocks ISA accounts, not CFDs (24 Oct 2026).
"""
from typing import Literal
import math
import re
import time
from .order_gate import OrderGateContext, evaluate_gate

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class OrderPreview(Strict):
    broker: Literal['Trading212-CFD', 'Trading212-Invest', 'Trading212-StocksISA']
    symbol: str = Field(min_length=1, max_length=50)
    direction: Literal['BUY', 'SELL']
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    point_value: float = Field(gt=0, description='Cash P&L per 1 price unit per quantity, in account currency')
    estimated_total_cost: float = Field(ge=0, description='Illustrative commission, spread and slippage in account currency')
    account_equity: float = Field(gt=0)
    risk_budget_percent: float = Field(gt=0, le=100)
    price_source: Literal['UNVERIFIED USER INPUT', 'HISTORICAL BID'] = 'UNVERIFIED USER INPUT'

    @model_validator(mode='after')
    def validate_direction(self):
        if not re.fullmatch(r'[A-Za-z0-9:_./+-]{1,50}', self.symbol):
            raise ValueError('Invalid symbol format')
        if self.direction == 'BUY' and self.stop_price >= self.entry_price:
            raise ValueError('A BUY protective stop must be below entry')
        if self.direction == 'SELL' and self.stop_price <= self.entry_price:
            raise ValueError('A SELL protective stop must be above entry')
        return self


def calculate_preview(body: OrderPreview) -> dict:
    """Pure mathematical estimate; never authorises a real or demo order."""
    stop_distance = abs(body.entry_price - body.stop_price)
    gross_loss_at_stop = stop_distance * body.quantity * body.point_value
    estimated_loss_at_stop = gross_loss_at_stop + body.estimated_total_cost
    budget = body.account_equity * body.risk_budget_percent / 100.0
    estimated_exposure = body.entry_price * body.quantity * body.point_value
    # Strictly positive inputs can still underflow to zero in float arithmetic.
    # A risk preview showing zero loss/exposure or a zero cash budget is misleading.
    if not all(math.isfinite(x) and x > 0 for x in (
        gross_loss_at_stop, estimated_loss_at_stop, budget, estimated_exposure
    )):
        raise ValueError('Risk calculation overflowed or underflowed')
    risk_fraction = 100 * estimated_loss_at_stop / body.account_equity
    # A finite loss divided by subnormal equity may overflow to infinity.
    # Reject it here instead of returning non-JSON infinity or a false pass.
    if not math.isfinite(risk_fraction) or risk_fraction <= 0:
        raise ValueError('Risk calculation overflowed or underflowed')
    permitted = estimated_loss_at_stop <= budget
    warnings = [
        'NO BROKER CONNECTED: this is a hypothetical calculation, not a quote or order.',
        'Stop loss is not guaranteed: gaps, spread widening and execution slippage can exceed this estimate.',
        'Trading212 Public API does not support CFD account orders.',
        'Point value and assumed costs must be verified against the exact instrument and account currency.',
        'No live execution is enabled. AI tokens cannot place orders.',
    ]
    if body.price_source == 'HISTORICAL BID':
        warnings.append('Historical bid candles cannot establish an executable entry/exit price or ask-side spread.')
    if not permitted:
        warnings.append('Illustrative risk exceeds the specified budget; do not treat this plan as acceptable.')
    return {
        'instrument': body.symbol,
        'broker': body.broker,
        'direction': body.direction,
        # Keep full JSON numeric precision: rounding to 4 decimals can turn a
        # positive micro-lot loss/budget into a misleading displayed zero.
        'estimated_exposure': estimated_exposure,
        'estimated_loss_if_filled_at_stop': estimated_loss_at_stop,
        'risk_budget_cash': budget,
        'estimated_risk_percent': risk_fraction,
        'within_user_risk_budget': permitted,
        'may_execute_real_order': False,
        'may_execute_paper_order': False,
        'quote_verified': False,
        'warnings': warnings,
    }



class StressPreview(OrderPreview):
    """Additional owner-provided assumptions for a conservative hypothetical scenario.

    This is NOT a broker margin check, worst-case guarantee, or executable quote.
    """
    stressed_exit_price: float = Field(gt=0)
    margin_requirement_percent: float = Field(gt=0, le=100)
    max_leverage: float = Field(gt=0, le=100)

    @model_validator(mode='after')
    def validate_stressed_exit(self):
        if self.direction == 'BUY' and self.stressed_exit_price >= self.stop_price:
            raise ValueError('A BUY stressed exit must be strictly below the protective stop')
        if self.direction == 'SELL' and self.stressed_exit_price <= self.stop_price:
            raise ValueError('A SELL stressed exit must be strictly above the protective stop')
        return self


def calculate_stress_preview(body: StressPreview) -> dict:
    """Fail-closed, zero-side-effect stress, leverage and margin assumptions."""
    base = calculate_preview(body)
    stressed_distance = abs(body.entry_price - body.stressed_exit_price)
    stressed_loss = stressed_distance * body.quantity * body.point_value + body.estimated_total_cost
    notional = body.entry_price * body.quantity * body.point_value
    assumed_margin = notional * body.margin_requirement_percent / 100
    effective_leverage = notional / body.account_equity
    stressed_risk_percent = 100 * stressed_loss / body.account_equity
    values = (stressed_loss, notional, assumed_margin, effective_leverage, stressed_risk_percent)
    # Underflowed margin/leverage must not be reported as zero and pass the
    # corresponding limits. The stress scenario has strictly positive inputs.
    if not all(math.isfinite(x) and x > 0 for x in values):
        raise ValueError('Stress calculation overflowed or underflowed')

    # Compare with the unrounded cash budget to avoid approval near a rounding boundary.
    stress_within_budget = stressed_loss <= body.account_equity * body.risk_budget_percent / 100
    # Initial-equity margin/leverage can pass even though the hypothetical
    # stop-gap loss leaves insufficient equity to support the same exposure.
    # Keep the initial leverage metric for compatibility, but gate on stressed
    # equity. A rounded-away loss is not evidence of safe remaining equity.
    stressed_equity = body.account_equity - stressed_loss
    stressed_equity_positive = (math.isfinite(stressed_equity)
                                and 0 < stressed_equity < body.account_equity)
    stressed_leverage = (notional / stressed_equity
                         if stressed_equity_positive else float('nan'))
    stressed_leverage_valid = (math.isfinite(stressed_leverage)
                               and stressed_leverage > 0)
    margin_covered = stressed_equity_positive and assumed_margin <= stressed_equity
    leverage_within_limit = (stressed_leverage_valid
                             and stressed_leverage <= body.max_leverage)
    all_checks = (base['within_user_risk_budget'] and stress_within_budget
                  and stressed_equity_positive and margin_covered
                  and leverage_within_limit)
    warnings = list(base['warnings'])
    warnings.extend([
        'Stressed exit is user-supplied; worse gaps, partial fills, spread widening and outages can cause larger losses.',
        'Margin percentage and leverage cap are user assumptions, NOT broker-verified rules or liquidation estimates.',
        'Estimated notional and margin depend on exact contract value and account-currency conversion.',
    ])
    if not stress_within_budget:
        warnings.append('The stressed stop-gap loss exceeds the specified risk budget.')
    if not stressed_equity_positive:
        warnings.append('Stressed equity is exhausted or cannot be calculated safely.')
    if not margin_covered:
        warnings.append('Illustrative margin requirement exceeds remaining stressed equity.')
    if not leverage_within_limit:
        warnings.append('Illustrative stressed-equity leverage exceeds the selected cap.')
    if stressed_loss > body.account_equity:
        warnings.append('The selected stress scenario loses more than the assumed account equity.')
    return {
        **base,
        'stressed_exit_price': body.stressed_exit_price,
        'stressed_loss_if_filled': stressed_loss,
        'stressed_risk_percent': stressed_risk_percent,
        'stressed_loss_within_budget': stress_within_budget,
        'assumed_margin_required': assumed_margin,
        'assumed_margin_covered_by_equity': margin_covered,
        'assumed_effective_leverage': effective_leverage,
        'stressed_equity_remaining_cash': stressed_equity if math.isfinite(stressed_equity) else None,
        'stressed_equity_positive': stressed_equity_positive,
        'assumed_stressed_effective_leverage': (
            stressed_leverage if stressed_leverage_valid else None
        ),
        'within_user_leverage_cap': leverage_within_limit,
        'all_hypothetical_limits_pass': all_checks,
        'may_execute_real_order': False,
        'may_execute_paper_order': False,
        'quote_verified': False,
        'warnings': warnings,
    }



class OrderGatePreview(Strict):
    """Owner-declared quote/risk assumptions; NOT a live order authorisation."""
    risk: StressPreview
    controls: OrderGateContext


def calculate_order_gate_preview(body: OrderGatePreview, now_ms: int) -> dict:
    """No writes, orders, broker requests, secrets or quote authentication."""
    stress = calculate_stress_preview(body.risk)
    gate = evaluate_gate(body.controls, now_ms)
    quote = body.controls.quote
    checks = dict(gate['checks'])
    checks['instrument_matches_order'] = (
        quote.instrument == body.risk.symbol
        and body.controls.expected_instrument == body.risk.symbol
    )
    # A hypothetical market entry may be worse than the current bid/ask, but
    # must never claim a more favorable entry than the owner-declared quote.
    checks['entry_not_optimistic_vs_quote'] = (
        body.risk.entry_price >= quote.ask if body.risk.direction == 'BUY'
        else body.risk.entry_price <= quote.bid
    )
    checks['hypothetical_stress_limits'] = stress['all_hypothetical_limits_pass']
    # A new order can breach a daily loss cap even when losses so far have
    # not reached it. Include the stressed hypothetical loss in the check.
    # Do not ignore other open positions' unrealized losses and incremental
    # reserved downside when projecting the account-wide daily loss.
    existing_daily_pnl = gate['effective_daily_pnl_after_existing_risk_cash']
    projected_daily_pnl = (
        existing_daily_pnl - stress['stressed_loss_if_filled']
        if existing_daily_pnl is not None else float('nan')
    )
    checks['projected_daily_loss_within_cap'] = (
        math.isfinite(projected_daily_pnl)
        and projected_daily_pnl > -body.controls.max_daily_loss_cash
    )
    # Independently cap this single position's stressed cash loss. The daily
    # cap and percentage-of-equity budget do not replace an explicit per-order
    # cash ceiling. Missing owner-declared policy fails closed (HTTP stays 200
    # because this is a non-executing diagnostic, never an order sender).
    position_cap = body.controls.max_position_loss_cash
    checks['position_loss_cap_supplied'] = position_cap is not None
    checks['position_loss_cap_within_daily_limit'] = (
        position_cap is not None and position_cap <= body.controls.max_daily_loss_cash
    )
    checks['position_loss_cap_within_equity'] = (
        position_cap is not None and position_cap <= body.risk.account_equity
    )
    checks['stressed_position_loss_within_cap'] = (
        position_cap is not None and stress['stressed_loss_if_filled'] <= position_cap
    )
    checks['documented_account_api_support'] = body.risk.broker != 'Trading212-CFD'
    # Per-order margin/leverage checks cannot account for other positions.
    # This conservative portfolio preview adds owner-declared existing gross
    # exposure and reserved margin. The default zero means UNKNOWN, not
    # verified absence of other positions.
    reserved_margin = body.controls.other_positions_reserved_margin_cash
    existing_gross = body.controls.other_positions_gross_notional_cash
    proposed_margin = stress['assumed_margin_required']
    proposed_gross = stress['estimated_exposure']
    combined_margin = reserved_margin + proposed_margin
    combined_gross = existing_gross + proposed_gross
    # Current equity already includes marked P&L. Deduct only incremental
    # reserved downside on other positions, then the proposed stress loss;
    # never double-count already marked unrealized losses.
    portfolio_stressed_equity = (body.risk.account_equity
                                 - body.controls.other_positions_reserved_stress_loss_cash
                                 - stress['stressed_loss_if_filled'])
    portfolio_stressed_equity_valid = (
        math.isfinite(portfolio_stressed_equity)
        and 0 < portfolio_stressed_equity < body.risk.account_equity
        and (body.controls.other_positions_reserved_stress_loss_cash == 0
             or portfolio_stressed_equity < stress['stressed_equity_remaining_cash'])
    )
    combined_leverage = (combined_gross / portfolio_stressed_equity
                         if portfolio_stressed_equity_valid else float('nan'))
    # Detect both overflow and lost positive increments due to float rounding:
    # a new order must not disappear when added to a large existing exposure.
    margin_arithmetic_ok = math.isfinite(combined_margin) and combined_margin > reserved_margin
    notional_arithmetic_ok = (math.isfinite(combined_gross)
                              and combined_gross > existing_gross
                              and math.isfinite(combined_leverage)
                              and combined_leverage > 0)
    checks['portfolio_margin_arithmetic_valid'] = margin_arithmetic_ok
    checks['portfolio_gross_arithmetic_valid'] = notional_arithmetic_ok
    checks['portfolio_stressed_equity_positive'] = portfolio_stressed_equity_valid
    checks['portfolio_margin_within_equity'] = (
        margin_arithmetic_ok and portfolio_stressed_equity_valid
        and combined_margin <= portfolio_stressed_equity
    )
    checks['portfolio_gross_leverage_within_cap'] = (
        notional_arithmetic_ok and portfolio_stressed_equity_valid
        and combined_leverage <= body.risk.max_leverage
    )
    # Trading 212's official public API covers cash Invest/Stocks ISA only.
    # A SELL entry with a protective stop above entry represents opening a
    # short; this preview does not model reducing a verified long holding.
    # For a proposed BUY, require full account-equity coverage of total gross
    # exposure even if the owner supplied a looser leverage/margin assumption.
    # These checks are conservative declarations, NOT authenticated buying power.
    cash_account = body.risk.broker in ('Trading212-Invest', 'Trading212-StocksISA')
    checks['cash_account_no_short_entry'] = (
        not cash_account or body.risk.direction == 'BUY'
    )
    checks['cash_account_gross_fully_funded'] = (
        not cash_account or (
            notional_arithmetic_ok and portfolio_stressed_equity_valid
            and combined_gross <= portfolio_stressed_equity
        )
    )
    gate.update(
        checks=checks,
        failed_checks=[key for key, ok in checks.items() if not ok],
        assumption_checks_pass=all(checks.values()),
        server_evaluated_at_ms=now_ms,
        hypothetical_risk={
            'estimated_loss_if_filled_at_stop': stress['estimated_loss_if_filled_at_stop'],
            'stressed_loss_if_filled': stress['stressed_loss_if_filled'],
            'max_position_loss_cash': position_cap,
            'position_cap_broker_verified': False,
            'assumed_margin_required': stress['assumed_margin_required'],
            'all_hypothetical_limits_pass': stress['all_hypothetical_limits_pass'],
            'stressed_equity_remaining_cash': stress['stressed_equity_remaining_cash'],
        },
        account_wide_daily_loss_scenario={
            'realized_pnl_cash': body.controls.daily_realized_pnl_cash,
            'unrealized_loss_cash': min(body.controls.daily_unrealized_pnl_cash, 0.0),
            'other_positions_reserved_stress_loss_cash': (
                body.controls.other_positions_reserved_stress_loss_cash
            ),
            'effective_pnl_before_proposed_order_cash': existing_daily_pnl,
            'projected_pnl_after_proposed_stress_cash': (
                projected_daily_pnl if math.isfinite(projected_daily_pnl) else None
            ),
        },
        portfolio_exposure_scenario={
            'other_positions_reserved_margin_cash': reserved_margin,
            'other_positions_gross_notional_cash': existing_gross,
            'proposed_margin_cash': proposed_margin,
            'proposed_gross_notional_cash': proposed_gross,
            'combined_margin_cash': combined_margin if math.isfinite(combined_margin) else None,
            'remaining_stressed_equity_cash': (
                portfolio_stressed_equity if math.isfinite(portfolio_stressed_equity) else None
            ),
            'combined_gross_notional_cash': combined_gross if math.isfinite(combined_gross) else None,
            'combined_gross_leverage': combined_leverage if math.isfinite(combined_leverage) else None,
            'inputs_broker_verified': False,
        },
        broker_connection_verified=False,
        may_execute_real_order=False,
        may_execute_paper_order=False,
        warnings=gate['warnings'] + [
            'Even a fully passing preview uses owner-declared inputs, not a signed provider feed.',
            'The broker is NOT connected; per-order owner confirmation and a durable, atomic kill switch are not implemented.',
            'Portfolio gross exposure and margin reservations are owner-declared; defaults of zero do not verify that the account has no other positions.',
            'Margin, cash funding and leverage are checked against remaining hypothetical stressed equity, not broker buying power.',
        ],
    )
    return gate

def build_router(owner):
    router = APIRouter(prefix='/api/broker', tags=['Broker Readiness'])

    @router.get('/capabilities')
    def capabilities(auth=Depends(owner)):
        return {
            'status': 'NO BROKER CONNECTION',
            'execution_mode': 'RESEARCH-ONLY',
            'quote_verified': False,
            'account_linked': False,
            'live_orders_enabled': False,
            'demo_orders_enabled': False,
            'risk_preview_enabled': True,
            'brokers': [
                {'id':'Trading212-CFD', 'api_order_support':False, 'integration_status':'OFFICIAL PUBLIC API UNSUPPORTED'},
                {'id':'Trading212-Invest', 'api_order_support':True, 'integration_status':'ELIGIBLE API EXISTS; NOT CONNECTED'},
                {'id':'Trading212-StocksISA', 'api_order_support':True, 'integration_status':'ELIGIBLE API EXISTS; NOT CONNECTED'},
            ],
            'source_url':'https://docs.trading212.com/api',
        }

    @router.post('/order-risk-preview')
    def order_risk_preview(body: OrderPreview, auth=Depends(owner)):
        try:
            return calculate_preview(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post('/stress-preview')
    def stress_preview(body: StressPreview, auth=Depends(owner)):
        try:
            return calculate_stress_preview(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None


    @router.post('/order-gate-preview')
    def order_gate_preview(body: OrderGatePreview, auth=Depends(owner)):
        try:
            return calculate_order_gate_preview(body, time.time_ns() // 1_000_000)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    return router