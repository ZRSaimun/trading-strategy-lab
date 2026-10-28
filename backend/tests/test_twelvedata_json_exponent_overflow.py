"""Synthetic JSON exponent-overflow integrity checks; no provider account or network."""
import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.providers.twelvedata import ProviderError, retrieve

T = 1790000040
KEY = "synthetic-test-key"


def _payload():
    return {
        "status": "ok",
        "meta": {"symbol": "XAU/USD", "interval": "1min", "exchange_timezone": "UTC"},
        "values": [{
            "datetime": datetime.fromtimestamp(T, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "open": "2000", "high": "2002", "low": "1999", "close": "2001",
        }],
    }


def _retrieve_json(raw):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"Content-Type": "application/json"},
            content=raw.encode("utf-8"),
        )

    try:
        result = asyncio.run(retrieve(
            KEY, "XAUUSD-TD", 1, T, T + 120,
            transport=httpx.MockTransport(handler), include_wire_evidence=True,
        ))
        return result, requests
    except ProviderError as exc:
        return exc, requests


@pytest.mark.parametrize("location,number", [
    ("extra", "1e400"),
    ("extra", "-1e400"),
    ("meta", "1e400"),
    ("price", "1e400"),
])
def test_json_exponent_overflow_is_quarantined_even_in_ignored_fields(location, number):
    payload = _payload()
    if location == "extra":
        payload["untrusted_extra"] = "__OVERFLOW__"
    elif location == "meta":
        payload["meta"]["untrusted_extra"] = "__OVERFLOW__"
    else:
        payload["values"][0]["close"] = "__OVERFLOW__"
    raw = json.dumps(payload).replace('"__OVERFLOW__"', number)
    error, requests = _retrieve_json(raw)
    assert len(requests) == 1
    assert isinstance(error, ProviderError)
    assert error.status == 502
    assert str(error) == "Provider request failed or returned invalid JSON; no data imported."
    assert KEY not in str(error)


def test_finite_json_exponent_remains_accepted():
    payload = _payload()
    payload["values"][0]["close"] = "__FINITE__"
    raw = json.dumps(payload).replace('"__FINITE__"', "2.001e3")
    result, requests = _retrieve_json(raw)
    assert len(requests) == 1
    assert not isinstance(result, ProviderError)
    rows, archive, wire = result
    assert len(rows) == 1
    assert rows[0]["close"] == 2001.0
    assert wire["decoded_http_body_bytes"] == len(raw.encode("utf-8"))
    assert b"XAU/USD" in archive
