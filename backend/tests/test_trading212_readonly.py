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
    {"endpoint": []}, {"environment": []}, {"endpoint": "orders"}, {"endpoint": "/api/v0/equity/orders/market"},
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
    httpx.Response(200, json={}, headers={"content-length": "9"*10000}),
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


def test_broker_rate_limit_headers_are_observations_not_permissions():
    headers = {
        "x-ratelimit-limit": "50",
        "x-ratelimit-period": "60",
        "x-ratelimit-remaining": "49",
        "x-ratelimit-reset": "1793030400",
        "x-ratelimit-used": "1",
    }
    result = call(lambda _: httpx.Response(200, json=[], headers=headers))
    quota = result["rate_limit_observation"]
    assert quota["status"] == "OBSERVED_UNVERIFIED"
    assert quota["remaining"] == 49 and quota["used"] == 1
    assert quota["account_quota_verified"] is False
    assert quota["safe_to_make_another_request"] is False
    assert result["market_data_feed"] is False and result["may_execute_order"] is False


def test_broker_missing_and_partial_quota_headers_do_not_claim_capacity():
    missing = call(lambda _: httpx.Response(200, json=[]))
    assert missing["rate_limit_observation"]["status"] == "MISSING_REVIEW_REQUIRED"
    assert missing["rate_limit_observation"]["remaining"] is None
    partial = call(lambda _: httpx.Response(
        200, json=[], headers={"x-ratelimit-limit": "50"}))
    assert partial["rate_limit_observation"]["status"] == "PARTIAL_REVIEW_REQUIRED"
    assert partial["rate_limit_observation"]["safe_to_make_another_request"] is False


@pytest.mark.parametrize("headers", [
    {"x-ratelimit-limit": "10", "x-ratelimit-period": "60",
     "x-ratelimit-remaining": "10", "x-ratelimit-reset": "1793030400",
     "x-ratelimit-used": "1"},
    {"x-ratelimit-limit": "0", "x-ratelimit-period": "60",
     "x-ratelimit-remaining": "0", "x-ratelimit-reset": "1793030400",
     "x-ratelimit-used": "0"},
    {"x-ratelimit-limit": "10", "x-ratelimit-period": "0",
     "x-ratelimit-remaining": "9", "x-ratelimit-reset": "1793030400",
     "x-ratelimit-used": "1"},
    {"x-ratelimit-limit": "10", "x-ratelimit-period": "60",
     "x-ratelimit-remaining": "9", "x-ratelimit-reset": "0",
     "x-ratelimit-used": "1"},
])
def test_inconsistent_broker_rate_limit_counters_require_review(headers):
    result = call(lambda _: httpx.Response(200, json=[], headers=headers))
    assert result["rate_limit_observation"]["status"] == "INCONSISTENT_REVIEW_REQUIRED"
    assert result["rate_limit_observation"]["safe_to_make_another_request"] is False


@pytest.mark.parametrize("headers", [
    {"x-ratelimit-limit": "10,11"},
    {"x-ratelimit-limit": "not-a-number"},
    {"x-ratelimit-limit": "-1"},
    {"x-ratelimit-limit": "1.0"},
    {"x-ratelimit-limit": "9" * 100},
    [("x-ratelimit-limit", "10"), ("x-ratelimit-limit", "11")],
])
def test_malformed_or_duplicate_broker_quota_headers_fail_closed(headers):
    with pytest.raises(ReadOnlyBrokerError, match="rate-limit headers"):
        call(lambda _: httpx.Response(200, json=[], headers=headers))


def test_broker_quota_evidence_never_includes_authentication_header():
    result = call(lambda _: httpx.Response(
        200, json={}, headers={
            "x-ratelimit-limit": "2", "x-ratelimit-period": "60",
            "x-ratelimit-remaining": "1", "x-ratelimit-reset": "1793030400",
            "x-ratelimit-used": "1", "authorization": "secret-not-for-output",
        }))
    assert "secret-not-for-output" not in json.dumps(result)


@pytest.mark.parametrize("body", [
    b"\xef\xbb\xbf{}",  # UTF-8 BOM is not valid RFC 8259 JSON wire encoding
    "{}".encode("utf-16"),
    "{}".encode("utf-32"),
    b'{"name":"\xff"}',  # invalid UTF-8
])
def test_broker_json_rejects_non_utf8_and_bom_without_leaking_body(body):
    with pytest.raises(ReadOnlyBrokerError, match="Invalid broker JSON") as exc:
        call(lambda _: httpx.Response(
            200, content=body, headers={"content-type": "application/json"}
        ))
    assert "name" not in str(exc.value)


def test_broker_json_accepts_strict_utf8_non_ascii_without_feed_claim():
    body = '{"name":"Café","currency":"EUR"}'.encode("utf-8")
    result = call(lambda _: httpx.Response(
        200, content=body, headers={"content-type": "application/json"}
    ))
    assert result["data"] == {"name": "Café", "currency": "EUR"}
    assert result["market_data_feed"] is False
    assert result["price_freshness_verified"] is False
    assert result["may_execute_order"] is False


@pytest.mark.parametrize("body", [
    b'{"ticker":"\\ud800"}',        # isolated high surrogate in a value
    b'{"\\udfff":"example"}',       # isolated low surrogate in an object key
    b'[{"nested":["\\udc00"]}]',   # nested list value
    b'{"ticker":"\\ud83d"}',       # incomplete surrogate pair
])
def test_broker_json_rejects_unpaired_surrogate_escapes(body):
    with pytest.raises(ReadOnlyBrokerError, match="Invalid broker JSON") as exc:
        call(lambda _: httpx.Response(
            200, content=body, headers={"content-type": "application/json"}
        ))
    assert "ticker" not in str(exc.value)
    assert "example" not in str(exc.value)


@pytest.mark.parametrize("body", [
    b'{"symbol":"\\ud83d\\ude80"}',  # paired escapes are a valid scalar
    '{"symbol":"🚀"}'.encode("utf-8"),
])
def test_broker_json_accepts_valid_supplementary_unicode(body):
    result = call(lambda _: httpx.Response(
        200, content=body, headers={"content-type": "application/json"}
    ))
    assert result["data"] == {"symbol": "🚀"}
    assert result["market_data_feed"] is False
    assert result["may_execute_order"] is False


@pytest.mark.parametrize("headers", [
    {"content-type": "application/json; charset=latin1"},
    {"content-type": "application/json; charset=utf-16"},
    {"content-type": "application/json; charset=utf-8; foo=bar"},
    {"content-type": "application/json; charset=utf-8; charset=utf-8"},
    {"content-type": "application/json, application/json"},
    [("content-type", "application/json"), ("content-type", "application/json")],
])
def test_broker_rejects_ambiguous_or_non_utf8_json_media(headers):
    with pytest.raises(ReadOnlyBrokerError, match="content type"):
        call(lambda _: httpx.Response(200, content=b"{}", headers=headers))


@pytest.mark.parametrize("headers", [
    {"content-encoding": "gzip"},
    {"content-encoding": "identity, gzip"},
    [("content-encoding", "identity"), ("content-encoding", "identity")],
])
def test_broker_rejects_ambiguous_or_unsupported_content_coding(headers):
    headers = list(headers.items()) if isinstance(headers, dict) else headers
    headers.append(("content-type", "application/json"))
    with pytest.raises(ReadOnlyBrokerError, match="Compressed or ambiguous"):
        call(lambda _: httpx.Response(200, content=b"{}", headers=headers))


@pytest.mark.parametrize("headers", [
    [("content-length", "2"), ("content-length", "2")],
    [("content-length", "2"), ("content-length", "3")],
    {"content-length": "2, 2"},
])
def test_broker_rejects_duplicate_or_comma_joined_content_lengths(headers):
    headers = list(headers.items()) if isinstance(headers, dict) else headers
    headers.append(("content-type", "application/json"))
    with pytest.raises(ReadOnlyBrokerError, match="length|size limit"):
        call(lambda _: httpx.Response(200, content=b"{}", headers=headers))


@pytest.mark.parametrize("media", [
    "application/json",
    "application/json; charset=utf-8",
    'application/json; charset="UTF-8"',
    "Application/JSON ; charset = UTF-8",
])
def test_broker_accepts_unambiguous_utf8_json_media(media):
    result = call(lambda _: httpx.Response(
        200, content=b'{"ticker":"TEST"}',
        headers={"content-type": media, "content-encoding": "identity"},
    ))
    assert result["data"] == {"ticker": "TEST"}
    assert result["market_data_feed"] is False
    assert result["may_execute_order"] is False
