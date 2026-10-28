"""Synthetic Trading 212 GET-only transport-length checks; no broker calls."""
import httpx
import pytest

from app.trading212_readonly import ReadOnlyBrokerError, fetch_trading212_readonly


def _call(response):
    return fetch_trading212_readonly(
        endpoint="instruments", api_key="mock_key", api_secret="mock_secret",
        account_type="INVEST", environment="DEMO",
        transport=httpx.MockTransport(lambda request: response),
    )


@pytest.mark.parametrize("body", [b"{}", b"[]", b'{"ticker":"EXAMPLE"}'])
def test_matching_declared_length_accepts_only_mock_json(body):
    result = _call(httpx.Response(
        200, content=body,
        headers={"content-type": "application/json", "content-length": str(len(body))},
    ))
    assert result["market_data_feed"] is False
    assert result["may_execute_order"] is False


@pytest.mark.parametrize("declared", ["0", "1", "3", "999"])
def test_mismatched_declared_length_fails_closed_even_for_valid_json(declared):
    with pytest.raises(ReadOnlyBrokerError, match="Broker response length mismatch"):
        _call(httpx.Response(
            200, content=b"{}",
            headers={"content-type": "application/json", "content-length": declared},
        ))


def test_streamed_identity_body_length_mismatch_fails_closed():
    with pytest.raises(ReadOnlyBrokerError, match="Broker response length mismatch"):
        _call(httpx.Response(
            200, stream=httpx.ByteStream(b'{"ok":true}'),
            headers={"content-type": "application/json", "content-length": "2"},
        ))


def test_mismatch_does_not_echo_private_response_or_credentials():
    body = b'{"private_account":"sensitive_value"}'
    with pytest.raises(ReadOnlyBrokerError) as error:
        _call(httpx.Response(
            200, content=body,
            headers={"content-type": "application/json", "content-length": "2"},
        ))
    assert "sensitive_value" not in str(error.value)
    assert "mock_secret" not in str(error.value)
