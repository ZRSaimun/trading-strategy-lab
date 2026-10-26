"""Offline bounded Twelve Data decoded HTTP body provenance tests."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.providers.twelvedata import ProviderError, retrieve

T = 1790000040


def _body():
    values = []
    for t in (T, T + 60):
        values.append({
            "datetime": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "open": "100", "high": "102", "low": "99", "close": "101",
        })
    return json.dumps({
        "status": "ok",
        "meta": {"symbol": "XAU/USD", "interval": "1min", "exchange_timezone": "UTC"},
        "values": values,
    }, separators=(",", ":")).encode()


def _run(body, *, evidence):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})
    transport = httpx.MockTransport(handler)
    result = asyncio.run(retrieve(
        "synthetic-key", "XAUUSD-TD", 2, T + 60, T + 180,
        transport=transport, include_wire_evidence=evidence,
    ))
    return result, requests


def test_opt_in_digest_is_of_provider_decoded_body_not_normalized_snapshot():
    body = _body()
    (rows, snapshot, wire), requests = _run(body, evidence=True)
    assert len(requests) == 1
    assert requests[0].url.host == "api.twelvedata.com"
    assert requests[0].url.path == "/time_series"
    assert requests[0].headers["Authorization"] == "apikey synthetic-key"
    assert [r["time"] for r in rows] == [T, T + 60]
    assert wire == {
        "decoded_http_body_sha256": hashlib.sha256(body).hexdigest(),
        "decoded_http_body_bytes": len(body),
        "normalized_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "http_status": 200,
    }
    assert wire["decoded_http_body_sha256"] != wire["normalized_snapshot_sha256"]
    assert b"synthetic-key" not in snapshot


def test_default_historical_return_shape_unchanged():
    result, requests = _run(_body(), evidence=False)
    assert len(result) == 2
    assert len(requests) == 1


def test_invalid_evidence_mode_refused_before_any_http_call():
    transport = httpx.MockTransport(lambda request: pytest.fail("No request expected"))
    with pytest.raises(ProviderError, match="Invalid wire evidence mode"):
        asyncio.run(retrieve(
            "synthetic-key", "XAUUSD-TD", 2, T + 60, T + 180,
            transport=transport, include_wire_evidence=1,
        ))


def test_invalid_vendor_body_rejected_without_provenance_report():
    with pytest.raises(ProviderError):
        _run(b'{"status":"ok","meta":{},"values":[]}', evidence=True)
