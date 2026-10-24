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
    margin_covered = assumed_margin <= body.account_equity
    leverage_within_limit = effective_leverage <= body.max_leverage
    all_checks = (base['within_user_risk_budget'] and stress_within_budget
                  and margin_covered and leverage_within_limit)
    warnings = list(base['warnings'])
    warnings.extend([
        'Stressed exit is user-supplied; worse gaps, partial fills, spread widening and outages can cause larger losses.',
        'Margin percentage and leverage cap are user assumptions, NOT broker-verified rules or liquidation estimates.',
        'Estimated notional and margin depend on exact contract value and account-currency conversion.',
    ])
    if not stress_within_budget:
        warnings.append('The stressed stop-gap loss exceeds the specified risk budget.')
    if not margin_covered:
        warnings.append('Illustrative margin requirement exceeds hypothetical account equity.')
    if not leverage_within_limit:
        warnings.append('Illustrative leverage exceeds the selected cap.')
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
    checks['documented_account_api_support'] = body.risk.broker != 'Trading212-CFD'
    gate.update(
        checks=checks,
        failed_checks=[key for key, ok in checks.items() if not ok],
        assumption_checks_pass=all(checks.values()),
        server_evaluated_at_ms=now_ms,
        hypothetical_risk={
            'estimated_loss_if_filled_at_stop': stress['estimated_loss_if_filled_at_stop'],
            'stressed_loss_if_filled': stress['stressed_loss_if_filled'],
            'assumed_margin_required': stress['assumed_margin_required'],
            'all_hypothetical_limits_pass': stress['all_hypothetical_limits_pass'],
        },
        broker_connection_verified=False,
        may_execute_real_order=False,
        may_execute_paper_order=False,
        warnings=gate['warnings'] + [
            'Even a fully passing preview uses owner-declared inputs, not a signed provider feed.',
            'The broker is NOT connected; per-order owner confirmation and a durable, atomic kill switch are not implemented.',
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