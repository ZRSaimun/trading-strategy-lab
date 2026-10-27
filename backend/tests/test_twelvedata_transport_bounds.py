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
    compressed = gzip.compress(_body())
    with pytest.raises(ProviderError, match="invalid JSON"):
        _fetch(compressed, {"Content-Length": str(len(compressed))})



@pytest.mark.parametrize("declared_delta", [-1, 1, 10])
def test_declared_length_must_match_exact_received_entity_bytes(declared_delta):
    # A syntactically valid JSON response with a false length header must not
    # be accepted as complete evidence, even if a mock transport returns it.
    body = _body()
    with pytest.raises(ProviderError, match="Provider response length mismatch"):
        _fetch(body, {"Content-Length": str(len(body) + declared_delta)})


def test_content_length_and_transfer_encoding_together_fail_closed():
    # Ambiguous HTTP framing can be interpreted differently by intermediaries.
    body = _body()
    with pytest.raises(ProviderError, match="Conflicting provider response framing"):
        _fetch(body, {
            "Content-Length": str(len(body)),
            "Transfer-Encoding": "chunked",
        })


@pytest.mark.parametrize("transfer_encoding", [
    "gzip", "gzip, chunked", "chunked, gzip", "chunked, chunked",
    "compress", "identity", "", "chunked;invalid",
])
def test_unsupported_transfer_codings_fail_closed(transfer_encoding):
    # A transport can decode chunk framing, but must not silently accept
    # an unverified compression or ambiguous transfer-coding chain.
    with pytest.raises(ProviderError, match="Unsupported provider transfer encoding"):
        _fetch(_body(), {"Transfer-Encoding": transfer_encoding})


def test_duplicate_transfer_encoding_headers_fail_closed():
    with pytest.raises(ProviderError, match="Unsupported provider transfer encoding"):
        _fetch(_body(), [
            ("Transfer-Encoding", "chunked"),
            ("transfer-encoding", "chunked"),
        ])


@pytest.mark.parametrize("transfer_encoding", ["chunked", "CHUNKED"])
def test_single_chunked_transfer_encoding_is_supported(transfer_encoding):
    # httpx.MockTransport supplies the already transfer-decoded entity body.
    (rows, _, wire), _ = _fetch(
        _body(), {"Transfer-Encoding": transfer_encoding})
    assert len(rows) == 1
    assert wire["decoded_http_body_bytes"] == len(_body())


def test_absent_length_header_keeps_bounded_identity_stream_supported():
    body = _body()
    (rows, _, wire), _ = _fetch(body)
    assert len(rows) == 1
    assert wire["decoded_http_body_bytes"] == len(body)


@pytest.mark.parametrize("payload", [
    b"[" * 10000 + b"0" + b"]" * 10000,
    b'{"ignored":' + b"[" * 10000 + b"0" + b"]" * 10000 + b"}",
])
def test_excessively_nested_json_fails_closed_without_leaking_provider_details(payload):
    # Well below MAX_BYTES; Python's JSON decoder may raise RecursionError
    # before the adapter can validate the provider response shape.
    with pytest.raises(ProviderError, match="invalid JSON") as exc:
        _fetch(payload)
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


@pytest.mark.parametrize("limit", [True, False, 0, 5001, 1.5, "1", None])
def test_invalid_request_limit_is_rejected_before_provider_call(limit):
    # Avoid charging a provider or sending a distorted outputsize when callers
    # accidentally supply booleans, fractional numbers or strings.
    transport = httpx.MockTransport(lambda request: pytest.fail("No HTTP request expected"))
    with pytest.raises(ProviderError, match="integer count") as exc:
        asyncio.run(retrieve(
            "synthetic-only-key", "XAUUSD-TD", limit, T, T + 120,
            transport=transport,
        ))
    assert exc.value.status == 422


@pytest.mark.parametrize("end,now", [
    (float("nan"), T + 120),
    (float("inf"), T + 120),
    (float("-inf"), T + 120),
    ("1790000040", T + 120),
    (True, T + 120),
    (10 ** 30, T + 120),
    (10 ** 1000, T + 120),
    (T, float("nan")),
    (T, float("inf")),
    (T, None),
    (T, False),
    (T, 10 ** 30),
    (T, 10 ** 1000),
])
def test_invalid_utc_boundary_is_rejected_before_provider_call(end, now):
    transport = httpx.MockTransport(lambda request: pytest.fail("No HTTP request expected"))
    with pytest.raises(ProviderError, match="Invalid UTC request timestamp") as exc:
        asyncio.run(retrieve(
            "synthetic-only-key", "XAUUSD-TD", 1, end, now,
            transport=transport, include_wire_evidence=True,
        ))
    assert exc.value.status == 422


def test_valid_fractional_epoch_seconds_preserve_existing_boundary_behavior():
    # Epoch inputs may be fractional; the HTTP end_date remains second-precision.
    body = _body()
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(body))
    rows, _ = asyncio.run(retrieve(
        "synthetic-only-key", "XAUUSD-TD", 1, T + 0.5, T + 120.5,
        transport=httpx.MockTransport(handler),
    ))
    assert len(rows) == 1
    assert len(requests) == 1
    assert requests[0].url.params["end_date"] == datetime.fromtimestamp(
        T, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
