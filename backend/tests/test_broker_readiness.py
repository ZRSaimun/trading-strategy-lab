"""Owner-only, no-broker-side-effect order-risk preview regressions."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.broker_readiness import build_router, OrderPreview, calculate_preview


def payload(**changes):
    base = dict(broker='Trading212-CFD', symbol='XAUUSD', direction='BUY',
                entry_price=100, stop_price=98, quantity=2, point_value=1,
                estimated_total_cost=1, account_equity=1000, risk_budget_percent=1,
                price_source='HISTORICAL BID')
    return base | changes


def test_valid_risk_preview_is_not_real_execution():
    v = calculate_preview(OrderPreview(**payload()))
    assert v['estimated_loss_if_filled_at_stop'] == 5
    assert v['risk_budget_cash'] == 10
    assert v['within_user_risk_budget']
    assert v['estimated_risk_percent'] == 0.5
    assert v['may_execute_real_order'] is False
    assert v['quote_verified'] is False
    assert any('Historical bid' in msg for msg in v['warnings'])


def test_excessive_risk_warns_and_does_not_trade():
    v = calculate_preview(OrderPreview(**payload(quantity=20)))
    assert not v['within_user_risk_budget']
    assert v['may_execute_real_order'] is False
    assert any('exceeds' in msg for msg in v['warnings'])


def test_sell_direction_and_wrong_stop_rejected():
    good = calculate_preview(OrderPreview(**payload(direction='SELL',stop_price=105)))
    assert good['estimated_loss_if_filled_at_stop'] == 11
    for bad in (payload(direction='SELL',stop_price=99),payload(stop_price=101)):
        try:
            OrderPreview(**bad)
            assert False, 'Expected an invalid stop to be rejected'
        except ValueError:
            pass


def test_nonfinite_negative_and_unknown_broker_rejected():
    bad_cases = (payload(entry_price=float('nan')),
                 payload(account_equity=-10),
                 payload(quantity=-10),
                 payload(broker='Unrecognised'),
                 payload(symbol='BAD; DROP TABLE X'))
    for values in bad_cases:
        try:
            OrderPreview(**values)
            assert False, 'Invalid inputs must be rejected'
        except ValueError:
            pass


def test_authenticated_capabilities_and_no_mutations():
    app = FastAPI()
    app.include_router(build_router(lambda: 'owner'))
    client=TestClient(app)
    res=client.get('/api/broker/capabilities')
    assert res.status_code == 200
    assert not res.json()['live_orders_enabled']
    assert not res.json()['demo_orders_enabled']
    assert len(res.json()['brokers']) == 3
    assert client.post('/api/broker/order-risk-preview',json=payload()).status_code == 200
    assert client.post('/api/broker/order-risk-preview',json=payload(direction='SELL')).status_code == 422
    assert client.post('/api/broker/order',json=payload()).status_code == 404


def test_unauthenticated_cannot_request_preview():
    def deny():
        raise HTTPException(401, 'Authentication required')
    app=FastAPI()
    app.include_router(build_router(deny))
    client=TestClient(app)
    assert client.get('/api/broker/capabilities').status_code == 401
    assert client.post('/api/broker/order-risk-preview',json=payload()).status_code == 401