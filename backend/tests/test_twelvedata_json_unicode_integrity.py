"""Offline Unicode-scalar integrity regressions for Twelve Data JSON receipts."""
import asyncio
import json

import httpx
import pytest

from app.providers.twelvedata import ProviderError, retrieve


KEY = "synthetic-test-only"
NOW = 1700001000


def _payload():
    return {
        "status": "ok",
        "meta": {
            "symbol": "XAU/USD",
            "interval": "1min",
            "exchange_timezone": "UTC",
        },
        "values": [{
            "datetime": "2023-11-14 22:14:00",
            "open": "2000", "high": "2002",
            "low": "1999", "close": "2001",
        }],
    }


def _retrieve(payload):
    # ensure_ascii preserves the actual JSON \uXXXX escape spelling.
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "api.twelvedata.com"
        assert request.headers["Authorization"] == "apikey " + KEY
        return httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )

    try:
        result = asyncio.run(retrieve(
            KEY, "XAUUSD-TD", 1, NOW - 60, NOW,
            transport=httpx.MockTransport(handler), include_wire_evidence=True,
        ))
    except ProviderError as exc:
        result = exc
    return result, calls


@pytest.mark.parametrize("location", [
    "ignored_root_value",
    "ignored_meta_value",
    "ignored_candle_value",
    "ignored_root_key",
    "ignored_nested_key",
    "ignored_array_value",
])
def test_unpaired_surrogate_rejected_even_outside_normalized_fields(location):
    payload = _payload()
    if location == "ignored_root_value":
        payload["extra"] = "\ud800"
    elif location == "ignored_meta_value":
        payload["meta"]["extra"] = "\udfff"
    elif location == "ignored_candle_value":
        payload["values"][0]["extra"] = "\ud800"
    elif location == "ignored_root_key":
        payload["\ud800"] = "ignored"
    elif location == "ignored_nested_key":
        payload["meta"]["\udfff"] = "ignored"
    else:
        payload["extra"] = ["safe", {"inner": "\udfff"}]

    result, calls = _retrieve(payload)
    assert len(calls) == 1
    assert isinstance(result, ProviderError)
    assert result.status == 502
    assert str(result) == "Provider request failed or returned invalid JSON; no data imported."
    assert KEY not in str(result)


def test_valid_escaped_surrogate_pair_and_international_text_are_accepted():
    payload = _payload()
    payload["extra"] = {"emoji": "\ud83d\ude80", "city": "東京"}
    result, calls = _retrieve(payload)
    assert len(calls) == 1
    assert not isinstance(result, ProviderError)
    rows, archive, wire = result
    assert len(rows) == 1 and rows[0]["close"] == 2001.0
    assert wire["decoded_http_body_bytes"] > 0
    assert b"XAU/USD" in archive


def test_valid_bmp_unicode_scalar_is_accepted():
    payload = _payload()
    payload["extra"] = {"symbol": "\u2603"}
    result, calls = _retrieve(payload)
    assert len(calls) == 1
    assert not isinstance(result, ProviderError)
