"""Zero-network Twelve Data HTTP Date/Age provenance quarantine regressions."""
import asyncio
import json
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

from app.providers.twelvedata import ProviderError, retrieve


T = 1790000040
KEY = "synthetic-cache-test-key"


def _body():
    return json.dumps({
        "status": "ok",
        "meta": {
            "symbol": "XAU/USD", "interval": "1min",
            "exchange_timezone": "UTC",
        },
        "values": [{
            "datetime": datetime.fromtimestamp(T, timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "open": "2000", "high": "2002",
            "low": "1999", "close": "2001",
        }],
    }).encode("utf-8")


def _run(headers):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=_body(), headers=headers)

    try:
        result = asyncio.run(retrieve(
            KEY, "XAUUSD-TD", 1, T, T + 120,
            transport=httpx.MockTransport(handler),
            include_wire_evidence=True,
        ))
    except ProviderError as exc:
        result = exc
    return result, calls


def test_valid_canonical_date_and_zero_age_keep_historical_import_supported():
    date = format_datetime(datetime.fromtimestamp(T + 120, timezone.utc), usegmt=True)
    result, calls = _run({"Date": date, "Age": "0"})
    assert len(calls) == 1
    assert not isinstance(result, ProviderError)
    rows, _, wire = result
    assert len(rows) == 1 and rows[0]["close"] == 2001.0
    assert wire["http_status"] == 200
    assert "live" not in wire and "freshness_verified" not in wire


def test_missing_date_and_age_are_not_invented_or_required_for_history():
    result, calls = _run({})
    assert len(calls) == 1
    assert not isinstance(result, ProviderError)


def test_age_without_date_is_not_treated_as_signed_source_time():
    result, calls = _run({"Age": "15"})
    assert len(calls) == 1
    assert not isinstance(result, ProviderError)
    assert "provider_date" not in result[2]


@pytest.mark.parametrize("date", [
    "Thu, 29 Oct 2026 08:40:00 UTC",
    "Thu, 29 Oct 2026 08:40:00 +0000",
    "Thursday, 29-Oct-26 08:40:00 GMT",
    "Thu, 32 Oct 2026 08:40:00 GMT",
    "Thu, 29 Oct 2026 08:40:00 GMT, Thu, 29 Oct 2026 08:40:01 GMT",
    "Thu, 29 Oct 2026 08:40:00 GMT\\nAuthorization: secret",
    "Tue, 29 Oct 2026 08:40:00 GMT",  # incorrect weekday
])
def test_noncanonical_or_invalid_http_date_fails_closed(date):
    result, calls = _run({"Date": date})
    assert len(calls) == 1
    assert isinstance(result, ProviderError)
    assert result.status == 502
    assert str(result) == (
        "Provider request failed or returned invalid JSON; no data imported."
    )
    assert KEY not in str(result)


@pytest.mark.parametrize("age", [
    "-1", "1.0", "+1", "01", "1, 2", "1000000001",
    "99999999999", "infinite", "", "1 2",
])
def test_malformed_or_oversized_age_fails_closed(age):
    result, calls = _run({"Age": age})
    assert len(calls) == 1
    assert isinstance(result, ProviderError)
    assert result.status == 502
    assert KEY not in str(result)


@pytest.mark.parametrize("headers", [
    [("Date", "Thu, 29 Oct 2026 08:40:00 GMT"),
     ("date", "Thu, 29 Oct 2026 08:40:00 GMT")],
    [("Age", "0"), ("age", "0")],
])
def test_duplicate_cache_headers_fail_closed_even_when_values_match(headers):
    result, calls = _run(headers)
    assert len(calls) == 1
    assert isinstance(result, ProviderError)
    assert result.status == 502
