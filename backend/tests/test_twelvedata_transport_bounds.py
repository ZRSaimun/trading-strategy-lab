"""Mock-only Twelve Data HTTP entity-body bounds and encoding regressions."""
import asyncio
import gzip
import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.providers.twelvedata import MAX_BYTES, ProviderError, retrieve

T = 1790000040


def _body():
    values = [{
        "datetime": datetime.fromtimestamp(T, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "open": "100", "high": "102", "low": "99", "close": "101",
    }]
    return json.dumps({
        "status": "ok",
        "meta": {"symbol": "XAU/USD", "interval": "1min", "exchange_timezone": "UTC"},
        "values": values,
    }).encode()


def _fetch(body, headers=None, *, evidence=True):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(body), headers=headers or {})
    result = asyncio.run(retrieve(
        "synthetic-only-key", "XAUUSD-TD", 1, T, T + 120,
        transport=httpx.MockTransport(handler), include_wire_evidence=evidence,
    ))
    return result, seen


def test_identity_encoding_is_explicit_and_body_digest_is_exact():
    body = _body()
    (rows, _, wire), requests = _fetch(
        body, {"Content-Encoding": "identity", "Content-Length": str(len(body))})
    assert len(rows) == 1
    assert len(requests) == 1
    assert requests[0].headers["accept-encoding"] == "identity"
    assert wire["decoded_http_body_bytes"] == len(body)
    assert wire["decoded_http_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert wire["provider_credit_header_observation"]["status"] == "MISSING_REVIEW_REQUIRED"


@pytest.mark.parametrize("encoding", [
    "gzip", "deflate", "br", "gzip, identity", "identity, gzip",
])
def test_compressed_or_ambiguous_encoding_fails_closed(encoding):
    body = gzip.compress(_body()) if encoding == "gzip" else _body()
    with pytest.raises(ProviderError, match="Unsupported provider response encoding"):
        _fetch(body, {"Content-Encoding": encoding})


def test_duplicate_content_encoding_fails_closed():
    with pytest.raises(ProviderError, match="Unsupported provider response encoding"):
        _fetch(_body(), [
            ("Content-Encoding", "identity"), ("content-encoding", "identity"),
        ])


@pytest.mark.parametrize("length", ["3000001", "-1", "1.0", "not-a-number", "999999999"])
def test_invalid_or_oversized_declared_length_fails_closed(length):
    with pytest.raises(ProviderError, match="Invalid or oversized provider response length"):
        _fetch(_body(), {"Content-Length": length})


def test_duplicate_content_length_fails_closed():
    with pytest.raises(ProviderError, match="Invalid or oversized provider response length"):
        _fetch(_body(), [
            ("Content-Length", "10"), ("content-length", "10"),
        ])


def test_actual_oversized_uncompressed_body_fails_even_if_length_is_small():
    # Bounded mock payload; no vendor calls, decompression, or database writes.
    with pytest.raises(ProviderError, match="Provider response exceeded the safe size limit"):
        _fetch(b" " * (MAX_BYTES + 1), {"Content-Length": "1"})


def test_gzip_payload_without_encoding_header_is_not_silently_decoded():
    with pytest.raises(ProviderError, match="invalid JSON"):
        _fetch(gzip.compress(_body()), {"Content-Length": "100"})
