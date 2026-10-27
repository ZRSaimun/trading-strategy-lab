"""Synthetic provider OHLC type integrity; no account, network or price feed."""
import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.providers.twelvedata import ProviderError, normalize, retrieve

T = 1790000040
FIELDS = ("open", "high", "low", "close")


def _payload():
    return {
        "status": "ok",
        "meta": {"symbol": "XAU/USD", "interval": "1min", "exchange_timezone": "UTC"},
        "values": [{
            "datetime": datetime.fromtimestamp(T, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "open": "1", "high": "1", "low": "1", "close": "1",
        }],
    }


@pytest.mark.parametrize("field", FIELDS)
def test_true_provider_ohlc_is_not_silently_coerced_to_one(field):
    # float(True) == 1.0: previously a valid-looking positive Gold candle.
    payload = _payload()
    payload["values"][0][field] = True
    with pytest.raises(ProviderError, match="Invalid, duplicate or incomplete") as error:
        normalize(payload, "XAUUSD-TD", T + 120)
    assert error.value.status == 502


@pytest.mark.parametrize("invalid", [False, None, [], {}])
def test_other_non_numeric_json_scalars_are_rejected(invalid):
    payload = _payload()
    payload["values"][0]["open"] = invalid
    with pytest.raises(ProviderError, match="Invalid, duplicate or incomplete"):
        normalize(payload, "XAUUSD-TD", T + 120)


@pytest.mark.parametrize("value", ["1", 1, 1.0])
def test_existing_json_decimal_string_and_number_forms_remain_supported(value):
    payload = _payload()
    for field in FIELDS:
        payload["values"][0][field] = value
    rows, snapshot = normalize(payload, "XAUUSD-TD", T + 120)
    assert len(rows) == 1
    assert rows[0]["close"] == 1.0
    assert b"XAU/USD" in snapshot


def test_mock_http_boolean_price_fails_without_import_or_secret_leak():
    payload = _payload()
    payload["values"][0]["close"] = True
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"Content-Type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
        )

    with pytest.raises(ProviderError, match="Invalid, duplicate or incomplete") as error:
        asyncio.run(retrieve(
            "synthetic-only-key", "XAUUSD-TD", 1, T, T + 120,
            transport=httpx.MockTransport(handler), include_wire_evidence=True,
        ))
    assert len(requests) == 1
    assert "synthetic-only-key" not in str(error.value)
