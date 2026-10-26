import base64
import json

import httpx
import pytest

from app.trading212_readonly import ReadOnlyBrokerError, fetch_trading212_readonly


def call(handler, **kw):
    args = dict(endpoint="instruments", api_key="demo_key", api_secret="demo_secret",
                account_type="INVEST", transport=httpx.MockTransport(handler))
    args.update(kw)
    return fetch_trading212_readonly(**args)


def test_demo_metadata_only_get_fixed_host_and_no_orders():
    def handler(req):
        assert req.method == "GET"
        assert str(req.url) == "https://demo.trading212.com/api/v0/equity/metadata/instruments"
        assert req.headers["authorization"] == "Basic " + base64.b64encode(b"demo_key:demo_secret").decode()
        return httpx.Response(200, json=[{"ticker": "EXAMPLE"}])
    result = call(handler)
    assert result["data"] == [{"ticker": "EXAMPLE"}]
    assert result["market_data_feed"] is False
    assert result["may_execute_order"] is False
    assert result["account_type_verified"] is False
    assert len(result["response_sha256"]) == 64


def test_live_mode_still_only_reads():
    def handler(req):
        assert req.method == "GET"
        assert str(req.url) == "https://live.trading212.com/api/v0/equity/account/summary"
        return httpx.Response(200, json={"cash": 5})
    result = call(handler, environment="LIVE", endpoint="account_summary", account_type="STOCKS_ISA")
    assert result["environment"] == "LIVE" and result["may_execute_order"] is False


@pytest.mark.parametrize("changes", [
    {"endpoint": "orders"}, {"endpoint": "/api/v0/equity/orders/market"},
    {"environment": "UNKNOWN"}, {"account_type": "CFD"},
    {"api_key": "bad\nkey"}, {"api_key": "colon:key"},
    {"api_secret": ""}, {"api_secret": "bad\rsecret"},
])
def test_rejects_unsafe_requests_before_network(changes):
    def handler(_):
        pytest.fail("network must not be called")
    with pytest.raises(ReadOnlyBrokerError):
        call(handler, **changes)


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://attacker.example/"}),
    httpx.Response(401, text="secret-error-body"),
    httpx.Response(429, text="rate limited"),
    httpx.Response(200, text="not-json"),
    httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"}),
    httpx.Response(200, json=7),
    httpx.Response(200, json={}, headers={"content-length": str(9*1024*1024)}),
    httpx.Response(200, content=b"{" + b" "*(8*1024*1024) + b"}", headers={"content-type": "application/json"}),
])
def test_bad_responses_fail_closed_without_leaking_body(response):
    with pytest.raises(ReadOnlyBrokerError) as e:
        call(lambda _: response)
    assert "secret" not in str(e.value)
    assert "attacker" not in str(e.value)


def test_transport_errors_are_sanitized():
    def handler(_):
        raise httpx.ConnectError("demo_secret should never be reflected")
    with pytest.raises(ReadOnlyBrokerError) as e:
        call(handler)
    assert "demo_secret" not in str(e.value)
