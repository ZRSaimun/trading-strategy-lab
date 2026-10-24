"""Owner-only execution capability inventory and zero-side-effect risk previews.

No broker requests, orders, key storage or mutable account access. The public
Trading 212 API covers Invest/Stocks ISA accounts, not CFDs (24 Oct 2026).
"""
from typing import Literal
import math
import re

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
    if not all(math.isfinite(x) and x >= 0 for x in (gross_loss_at_stop, estimated_loss_at_stop, budget, estimated_exposure)):
        raise ValueError('Risk calculation overflowed')
    risk_fraction = 100 * estimated_loss_at_stop / body.account_equity
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
        'estimated_exposure': round(estimated_exposure, 4),
        'estimated_loss_if_filled_at_stop': round(estimated_loss_at_stop, 4),
        'risk_budget_cash': round(budget, 4),
        'estimated_risk_percent': round(risk_fraction, 4),
        'within_user_risk_budget': permitted,
        'may_execute_real_order': False,
        'may_execute_paper_order': False,
        'quote_verified': False,
        'warnings': warnings,
    }


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

    return router