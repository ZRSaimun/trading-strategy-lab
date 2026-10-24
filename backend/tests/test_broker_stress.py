"""Deterministic hypothetical gap, margin and leverage checks; no broker side effects."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.broker_readiness import (OrderPreview, StressPreview, calculate_preview,
                                  calculate_stress_preview, build_router)


def payload(**changes):
    data = dict(
        broker='Trading212-CFD', symbol='XAUUSD', direction='BUY',
        entry_price=100, stop_price=98, stressed_exit_price=95,
        quantity=2, point_value=1, estimated_total_cost=1,
        account_equity=1000, risk_budget_percent=1,
        margin_requirement_percent=10, max_leverage=2,
        price_source='HISTORICAL BID',
    )
    return data | changes


def test_gap_can_fail_budget_even_when_nominal_stop_passes():
    result = calculate_stress_preview(StressPreview(**payload()))
    assert result['estimated_loss_if_filled_at_stop'] == 5
    assert result['within_user_risk_budget'] is True
    assert result['stressed_loss_if_filled'] == 11
    assert result['stressed_loss_within_budget'] is False
    assert result['all_hypothetical_limits_pass'] is False
    assert result['assumed_margin_required'] == 20
    assert result['assumed_effective_leverage'] == 0.2
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False
    assert result['quote_verified'] is False


def test_all_hypothetical_limits_can_pass_without_authorising_orders():
    result = calculate_stress_preview(StressPreview(**payload(stressed_exit_price=96)))
    assert result['stressed_loss_if_filled'] == 9
    assert result['stressed_loss_within_budget'] is True
    assert result['all_hypothetical_limits_pass'] is True
    assert result['may_execute_real_order'] is False
    assert any('NOT broker-verified' in w for w in result['warnings'])


def test_leverage_and_margin_fail_independently():
    leverage = calculate_stress_preview(StressPreview(**payload(max_leverage=0.1)))
    assert not leverage['within_user_leverage_cap']
    assert leverage['assumed_margin_covered_by_equity']
    margin = calculate_stress_preview(StressPreview(**payload(
        entry_price=1000, stop_price=999, stressed_exit_price=998,
        quantity=2, margin_requirement_percent=100,
        max_leverage=10, risk_budget_percent=10,
    )))
    assert margin['assumed_margin_required'] == 2000
    assert not margin['assumed_margin_covered_by_equity']
    assert margin['within_user_leverage_cap']
    assert not margin['all_hypothetical_limits_pass']


def test_sell_gap_uses_worse_price_above_stop():
    result = calculate_stress_preview(StressPreview(**payload(
        direction='SELL', stop_price=102, stressed_exit_price=105,
    )))
    assert result['stressed_loss_if_filled'] == 11
    assert result['stressed_loss_within_budget'] is False


@pytest.mark.parametrize('changes', [
    {'stressed_exit_price': 98},
    {'stressed_exit_price': 99},
    {'direction': 'SELL', 'stop_price': 102, 'stressed_exit_price': 101},
    {'margin_requirement_percent': 0},
    {'margin_requirement_percent': 101},
    {'max_leverage': 0},
    {'max_leverage': float('nan')},
    {'stressed_exit_price': float('inf')},
])
def test_invalid_stress_inputs_are_rejected(changes):
    with pytest.raises(ValueError):
        StressPreview(**payload(**changes))


def test_extreme_values_fail_closed_without_overflowing_response():
    with pytest.raises(ValueError, match='overflowed'):
        calculate_stress_preview(StressPreview(**payload(
            entry_price=1e200, stop_price=1e199,
            stressed_exit_price=1e198, quantity=1e200,
        )))


@pytest.mark.parametrize('changes', [
    # Finite loss divided by subnormal equity must not produce JSON infinity.
    {'account_equity': 1e-320},
    # Strictly positive prices/quantity can multiply to zero in binary float.
    {'entry_price': 1e-320, 'stop_price': 5e-321,
     'stressed_exit_price': 1e-321, 'quantity': 1e-320,
     'estimated_total_cost': 0},
])
def test_numerically_unsafe_nominal_risk_fails_closed(changes):
    values = payload(**changes)
    with pytest.raises(ValueError, match='overflowed or underflowed'):
        calculate_preview(OrderPreview(**values))
    with pytest.raises(ValueError, match='overflowed or underflowed'):
        calculate_stress_preview(StressPreview(**values))


def test_subnormal_risk_returns_422_not_non_json_infinity():
    app = FastAPI()
    app.include_router(build_router(lambda: 'owner'))
    client = TestClient(app)
    for path in ('/api/broker/order-risk-preview', '/api/broker/stress-preview'):
        result = client.post(path, json=payload(account_equity=1e-320))
        assert result.status_code == 422
        assert 'overflowed or underflowed' in result.json()['detail']


def test_endpoint_requires_owner_and_never_exposes_order_action():
    app = FastAPI()
    app.include_router(build_router(lambda: 'owner'))
    client = TestClient(app)
    good = client.post('/api/broker/stress-preview', json=payload())
    assert good.status_code == 200
    assert good.json()['may_execute_real_order'] is False
    assert client.post('/api/broker/stress-preview', json=payload(stressed_exit_price=99)).status_code == 422
    assert client.post('/api/broker/order', json=payload()).status_code == 404

    def deny():
        raise HTTPException(401, 'Authentication required')

    locked = FastAPI()
    locked.include_router(build_router(deny))
    assert TestClient(locked).post('/api/broker/stress-preview', json=payload()).status_code == 401
