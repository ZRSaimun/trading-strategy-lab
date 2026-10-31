"""Synthetic wire-format regressions; never contact the broker."""
import gzip
import httpx
import pytest
from app.trading212_readonly import ReadOnlyBrokerError, fetch_trading212_readonly


def call(handler):
    return fetch_trading212_readonly(endpoint="instruments", api_key="mock_key", api_secret="mock_secret", account_type="INVEST", transport=httpx.MockTransport(handler))


def test_raw_json_and_identity_encoding_are_required():
    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, content=b'{"ticker":"EXAMPLE","tickSize":0.01}', headers={"content-type": "application/json"})
    result = call(handler)
    assert result["data"]["ticker"] == "EXAMPLE"
    assert result["may_execute_order"] is False


@pytest.mark.parametrize("payload", [
    b'{"ticker":"A","ticker":"B"}',
    b'{"nested":{"id":1,"id":2}}',
    b'{"price":NaN}',
    b'{"price":Infinity}',
    b'{"price":-Infinity}',
    b'{"price":1e999}',
    b'{"price":-1e999}',
])
def test_ambiguous_or_nonfinite_json_is_rejected(payload):
    with pytest.raises(ReadOnlyBrokerError, match="Invalid broker JSON"):
        call(lambda _: httpx.Response(200, content=payload, headers={"content-type": "application/json"}))


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "gzip, br"])
def test_compressed_response_is_rejected_before_decompression(encoding):
    body = gzip.compress(b'{"ticker":"EXAMPLE"}' * 100000)
    with pytest.raises(ReadOnlyBrokerError, match="Compressed broker responses not supported"):
        call(lambda _: httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type": "application/json", "content-encoding": encoding}))


def test_identity_response_exceeding_limit_is_rejected():
    body = b'{' + b' ' * (8*1024*1024) + b'}'
    with pytest.raises(ReadOnlyBrokerError, match="Broker response exceeds size limit"):
        call(lambda _: httpx.Response(200, content=body, headers={"content-type": "application/json"}))


def test_no_body_or_secret_leak_from_rejected_wire_response():
    with pytest.raises(ReadOnlyBrokerError) as exc:
        call(lambda _: httpx.Response(200, content=b'{"api_secret":"private","api_secret":"other"}', headers={"content-type": "application/json"}))
    assert "private" not in str(exc.value)
    assert "other" not in str(exc.value)
