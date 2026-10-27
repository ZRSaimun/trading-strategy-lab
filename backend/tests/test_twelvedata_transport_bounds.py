"""Mock-only Twelve Data HTTP entity-body bounds and encoding regressions."""
import asyncio
import gzip
import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.providers.twelvedata import MAX_BYTES, ProviderError, normalize, retrieve

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


@pytest.mark.parametrize("range_claim", [
    "bytes 0-9/100", "bytes */100", "", "bytes 0-99/*",
])
def test_successful_json_response_with_content_range_is_quarantined(range_claim):
    # 200 OK must be a full entity; a range claim makes provenance ambiguous
    # even if a mock returns valid-looking complete JSON bytes.
    with pytest.raises(ProviderError, match="partial-content claim") as exc:
        _fetch(_body(), {"Content-Range": range_claim})
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


def test_duplicate_content_range_headers_are_quarantined():
    with pytest.raises(ProviderError, match="partial-content claim"):
        _fetch(_body(), [
            ("Content-Range", "bytes 0-9/100"),
            ("content-range", "bytes 10-19/100"),
        ])


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


@pytest.mark.parametrize("end,now", [
    (-1, T + 120),
    (-0.5, T + 120),
    (T + 61, T + 120),
    (T + 120, T + 120),
    (T + 180, T + 120),
    (0, 59),
    (0, 0),
])
def test_incomplete_or_negative_historical_window_rejected_before_paid_call(end, now):
    # Direct adapter calls bypass the API route's end-time gate; they must
    # still refuse invalid windows without touching the provider or key.
    transport = httpx.MockTransport(lambda request: pytest.fail("No HTTP request expected"))
    with pytest.raises(ProviderError, match="completed UTC candle boundary") as exc:
        asyncio.run(retrieve(
            "synthetic-only-key", "XAUUSD-TD", 1, end, now,
            transport=transport, include_wire_evidence=True,
        ))
    assert exc.value.status == 422
    assert "synthetic-only-key" not in str(exc.value)


def test_exactly_completed_window_and_fractional_epoch_remain_valid():
    # No new minute-alignment restriction: callers may specify a fractional
    # epoch, as long as the final requested minute is already complete.
    body = _body()
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(body))
    rows, _ = asyncio.run(retrieve(
        "synthetic-only-key", "XAUUSD-TD", 1, T + 0.5, T + 60.5,
        transport=httpx.MockTransport(handler),
    ))
    assert len(rows) == 1
    assert len(requests) == 1

@pytest.mark.parametrize("media_type", [
    "text/html", "text/plain", "application/problem+json",
    "application/json; charset=iso-8859-1", "application/json, text/plain",
])
def test_explicit_non_json_or_ambiguous_media_type_is_rejected(media_type):
    # A 200 response containing valid-looking JSON cannot override an
    # explicitly conflicting HTTP media type.
    with pytest.raises(ProviderError, match="Unsupported provider response media type") as exc:
        _fetch(_body(), {"Content-Type": media_type})
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


def test_duplicate_content_type_headers_are_rejected():
    with pytest.raises(ProviderError, match="Unsupported provider response media type"):
        _fetch(_body(), [
            ("Content-Type", "application/json"),
            ("content-type", "application/json"),
        ])


@pytest.mark.parametrize("media_type", [
    "application/json", "Application/JSON",
    "application/json; charset=UTF-8",
    'application/json; charset="utf-8"',
])
def test_explicit_json_media_type_is_supported(media_type):
    (rows, _, wire), seen = _fetch(_body(), {"Content-Type": media_type})
    assert len(rows) == len(seen) == 1
    assert wire["decoded_http_body_bytes"] == len(_body())


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_multibyte_encoded_json_cannot_masquerade_as_utf8_provider_response(encoding):
    # json.loads(bytes) silently accepts UTF-16/UTF-32; the provider's
    # historical JSON entity must be UTF-8 before any candle is accepted.
    body = _body().decode("utf-8").encode(encoding)
    with pytest.raises(ProviderError, match="invalid JSON") as exc:
        _fetch(body, {"Content-Type": "application/json"})
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


@pytest.mark.parametrize("body", [
    b"\xef\xbb\xbf",
    b"\xff",
    b"\xc3\x28",
])
def test_bom_or_invalid_utf8_prefix_rejected_without_provider_details(body):
    with pytest.raises(ProviderError, match="invalid JSON") as exc:
        _fetch(body + _body(), {"Content-Type": "application/json; charset=UTF-8"})
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


def test_valid_utf8_non_ascii_json_remains_supported():
    payload = json.loads(_body().decode("utf-8"))
    payload["meta"]["synthetic_note"] = "caf\u00e9"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    (rows, _, wire), seen = _fetch(body, {"Content-Type": "application/json"})
    assert len(rows) == len(seen) == 1
    assert wire["decoded_http_body_sha256"] == hashlib.sha256(body).hexdigest()

@pytest.mark.parametrize("source_timestamp", [
    "2026-9-21 14:14:00",      # strptime accepts non-padded month
    "2026-09-21 4:14:00",      # strptime accepts non-padded hour
    "2026-09-21 14:4:00",      # strptime accepts non-padded minute
    "2026-09-21 14:14:0",      # strptime accepts non-padded seconds
    "２０２６-09-21 14:14:00", # Unicode digits must not masquerade as ASCII
    "2026-09-21 14:14:00Z",   # explicit timezone suffix is not the API contract
])
def test_noncanonical_provider_minute_timestamp_rejected(source_timestamp):
    # Historical source text must not be silently rewritten into a different
    # canonical UTC representation before snapshot hashing or gap assessment.
    payload = json.loads(_body())
    payload["values"][0]["datetime"] = source_timestamp
    with pytest.raises(ProviderError, match="Invalid, duplicate or incomplete") as exc:
        _fetch(json.dumps(payload).encode(), {"Content-Type": "application/json"})
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


def test_canonical_ascii_provider_minute_timestamp_still_accepted():
    (rows, _, wire), requests = _fetch(
        _body(), {"Content-Type": "application/json"})
    assert len(rows) == len(requests) == 1
    assert wire["decoded_http_body_sha256"] == hashlib.sha256(_body()).hexdigest()


@pytest.mark.parametrize("invalid_now", [
    float("nan"), float("inf"), float("-inf"),
    True, False, None, "1790000160",
    10 ** 1000, -1, 0, 59,
])
def test_direct_normalize_rejects_invalid_observation_clocks(invalid_now):
    # retrieve() already validates now, but direct normalization callers must
    # not accept NaN/+Infinity as evidence that future candles completed.
    payload = json.loads(_body())
    with pytest.raises(ProviderError, match="Invalid UTC observation timestamp") as exc:
        normalize(payload, "XAUUSD-TD", invalid_now)
    assert exc.value.status == 422
    assert "synthetic-only-key" not in str(exc.value)


def test_direct_normalize_preserves_valid_fractional_completed_minute_clock():
    payload = json.loads(_body())
    rows, snapshot = normalize(payload, "XAUUSD-TD", T + 60.5)
    assert len(rows) == 1
    assert rows[0]["time"] == T
    assert b"XAU/USD" in snapshot


def test_oversized_ohlc_csv_field_is_sanitized_by_direct_normalize():
    # JSON under the 3 MB transport bound can still exceed Python's CSV
    # per-field parser limit. Never propagate csv.Error as an HTTP 500.
    payload = json.loads(_body())
    payload["values"][0]["open"] = "1" * 140_000
    with pytest.raises(ProviderError, match="Invalid, duplicate or incomplete") as exc:
        normalize(payload, "XAUUSD-TD", T + 120)
    assert exc.value.status == 502
    assert "140000" not in str(exc.value)


def test_oversized_ohlc_csv_field_is_sanitized_by_http_adapter():
    payload = json.loads(_body())
    payload["values"][0]["close"] = "1" * 140_000
    body = json.dumps(payload).encode("utf-8")
    assert len(body) < MAX_BYTES
    with pytest.raises(ProviderError, match="Invalid, duplicate or incomplete") as exc:
        _fetch(body, {"Content-Type": "application/json"})
    assert exc.value.status == 502
    assert "synthetic-only-key" not in str(exc.value)


@pytest.mark.parametrize("bad_key", [
    None, True, 7, "", " ", "abc\ndef", "abc\rdef",
    "abc\tdef", "\x7f", "\u2603", "x" * 513,
])
def test_direct_retrieve_rejects_malformed_credential_before_network(bad_key):
    # A direct caller must not make a potentially chargeable request or leak
    # malformed credential bytes in the sanitized rejection.
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=_body())
    with pytest.raises(ProviderError, match="Invalid provider credential shape") as exc:
        asyncio.run(retrieve(
            bad_key, "XAUUSD-TD", 1, T, T + 120,
            transport=httpx.MockTransport(handler),
        ))
    assert exc.value.status == 422
    assert seen == []
    assert str(bad_key) not in str(exc.value)


def test_direct_retrieve_accepts_printable_ascii_key_boundary():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=_body())
    rows, _ = asyncio.run(retrieve(
        "x" * 512, "XAUUSD-TD", 1, T, T + 120,
        transport=httpx.MockTransport(handler),
    ))
    assert len(rows) == len(seen) == 1


@pytest.mark.parametrize("invalid_instrument", [
    None, True, 7, "", "XAUUSD-IMPORT", "XAUUSD-TD ", [], {},
])
def test_direct_normalize_rejects_unknown_or_unhashable_instrument(invalid_instrument):
    with pytest.raises(ProviderError, match="Unknown provider mapping") as exc:
        normalize(json.loads(_body()), invalid_instrument, T + 120)
    assert exc.value.status == 422


@pytest.mark.parametrize("invalid_instrument", [None, [], {}, "XAUUSD-IMPORT"])
def test_direct_retrieve_rejects_unknown_or_unhashable_instrument_before_network(invalid_instrument):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=_body())
    with pytest.raises(ProviderError, match="Unknown provider mapping") as exc:
        asyncio.run(retrieve(
            "synthetic-only-key", invalid_instrument, 1, T, T + 120,
            transport=httpx.MockTransport(handler),
        ))
    assert exc.value.status == 422
    assert seen == []
