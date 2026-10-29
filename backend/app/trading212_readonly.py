"""Opt-in Trading 212 Invest/ISA read-only REST client; not a market-data feed.

No background requests, persistence, order endpoints, or CFD support. Caller owns
credentials, account eligibility, permissions and any data usage rights.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from time import monotonic_ns
import hashlib
import json
import math
import re

import httpx

_HOSTS = {"DEMO": "https://demo.trading212.com", "LIVE": "https://live.trading212.com"}
_PATHS = {
    "instruments": "/api/v0/equity/metadata/instruments",
    "exchanges": "/api/v0/equity/metadata/exchanges",
    "account_summary": "/api/v0/equity/account/summary",
}
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ReadOnlyBrokerError(ValueError):
    """Sanitized broker read error; never contains keys or response bodies."""


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous JSON objects rather than accepting the last duplicate."""
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _reject_unpaired_surrogates(value: object) -> None:
    """Reject non-Unicode-scalar JSON strings, including nested object keys.

    JSON escapes can decode to isolated UTF-16 surrogate code points even
    when the HTTP response itself was valid UTF-8. Such values cannot be
    faithfully encoded as UTF-8 for downstream audit or storage.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise ValueError("unpaired JSON surrogate")
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonstandard JSON constant")


_JSON_CONTENT_TYPE = re.compile(
    r'application/json(?:\\s*;\\s*charset\\s*=\\s*(?:utf-8|"utf-8"))?',
    re.IGNORECASE,
)


def _identity_json_wire_headers(headers: httpx.Headers) -> str | None:
    """Validate single-valued JSON media, identity coding and body length.

    Reject ambiguous duplicate fields, misleading charset declarations and
    unsupported codings before reading any broker account payload.
    """
    media = headers.get_list("content-type")
    if len(media) != 1 or _JSON_CONTENT_TYPE.fullmatch(media[0].strip()) is None:
        raise ReadOnlyBrokerError("Unexpected broker response content type")

    codings = headers.get_list("content-encoding")
    if len(codings) > 1 or (codings and codings[0].strip().lower() != "identity"):
        raise ReadOnlyBrokerError("Compressed or ambiguous broker response not supported")

    lengths = headers.get_list("content-length")
    if len(lengths) > 1:
        raise ReadOnlyBrokerError("Ambiguous broker response length")
    size = lengths[0] if lengths else None
    if size is not None and (not size.isascii() or not size.isdecimal()
                             or len(size) > 8 or int(size) > _MAX_RESPONSE_BYTES):
        raise ReadOnlyBrokerError("Broker response exceeds size limit")
    return size


_RATE_HEADERS = (
    "x-ratelimit-limit", "x-ratelimit-period", "x-ratelimit-remaining",
    "x-ratelimit-reset", "x-ratelimit-used",
)


def _rate_limit_observation(headers: httpx.Headers) -> dict:
    """Observe, never trust, broker account-wide quota counters.

    No quota resets, account entitlements, or safe future request allowances
    can be inferred from unverified HTTP response headers.
    """
    observed = {}
    for name in _RATE_HEADERS:
        values = headers.get_list(name)
        if not values:
            observed[name] = None
            continue
        if len(values) != 1 or re.fullmatch(r"[0-9]{1,13}", values[0]) is None:
            raise ReadOnlyBrokerError("Invalid broker rate-limit headers")
        observed[name] = int(values[0])

    values = tuple(observed[name] for name in _RATE_HEADERS)
    if all(value is None for value in values):
        status = "MISSING_REVIEW_REQUIRED"
    elif any(value is None for value in values):
        status = "PARTIAL_REVIEW_REQUIRED"
    else:
        limit, period, remaining, reset, used = values
        if (not 1 <= limit <= 10_000_000 or not 1 <= period <= 86_400
                or not 0 <= remaining <= limit or not 0 <= used <= limit
                or not 1 <= reset <= 253402300799
                or used + remaining != limit):
            status = "INCONSISTENT_REVIEW_REQUIRED"
        else:
            status = "OBSERVED_UNVERIFIED"
    return {
        "status": status,
        "limit": values[0], "period_seconds": values[1],
        "remaining": values[2], "reset_unix_seconds": values[3],
        "used": values[4],
        "account_quota_verified": False,
        "safe_to_make_another_request": False,
    }


def _http_time_header_observation(headers: httpx.Headers, completed: datetime) -> dict:
    """Record untrusted HTTP Date/Age evidence without attesting source freshness.

    A Date header is an HTTP server assertion, not a signed issuance time.
    Age may indicate an intermediary cache. Neither can prove a live quote.
    """
    dates, ages = headers.get_list("date"), headers.get_list("age")
    if len(dates) > 1 or len(ages) > 1:
        raise ReadOnlyBrokerError("Ambiguous broker HTTP time headers")

    asserted_date = None
    if dates:
        value = dates[0]
        if len(value) > 40:
            raise ReadOnlyBrokerError("Invalid broker HTTP time headers")
        try:
            parsed = parsedate_to_datetime(value)
            if (parsed.tzinfo is None or parsed.utcoffset() != timedelta(0)
                    or format_datetime(parsed.astimezone(timezone.utc), usegmt=True) != value):
                raise ValueError("noncanonical HTTP Date")
        except (TypeError, ValueError, OverflowError):
            raise ReadOnlyBrokerError("Invalid broker HTTP time headers") from None
        asserted_date = parsed.astimezone(timezone.utc)

    age_seconds = None
    if ages:
        value = ages[0]
        if (len(value) > 13 or not value.isascii()
                or re.fullmatch(r"[0-9]+", value) is None):
            raise ReadOnlyBrokerError("Invalid broker HTTP time headers")
        age_seconds = int(value)

    offset_seconds = (
        (completed - asserted_date).total_seconds() if asserted_date is not None else None
    )
    disagreement = offset_seconds is not None and abs(offset_seconds) > 300
    if asserted_date is None:
        status = "MISSING_DATE_REVIEW_REQUIRED"
    elif disagreement:
        status = "LOCAL_CLOCK_DISAGREEMENT_REVIEW_REQUIRED"
    elif age_seconds is not None and age_seconds > 0:
        status = "AGE_HEADER_INDICATES_CACHE"
    else:
        status = "OBSERVED_UNVERIFIED"

    return {
        "status": status,
        "http_date_utc": asserted_date.isoformat() if asserted_date else None,
        "http_age_seconds": age_seconds,
        "local_completion_minus_http_date_seconds": offset_seconds,
        "local_clock_disagreement_over_300s": disagreement,
        "http_date_attested": False,
        "cache_freshness_verified": False,
        "may_use_as_market_timestamp": False,
    }


def fetch_trading212_readonly(
    *, endpoint: str, api_key: str, api_secret: str,
    account_type: str, environment: str = "DEMO",
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Perform one explicitly requested GET; return unpersisted JSON and caveats.

    A test-only injected transport can mock responses. Production uses httpx's
    default certificate validation, fixed HTTPS origins and no redirects/proxies.
    """
    if (not isinstance(endpoint, str) or endpoint not in _PATHS
            or not isinstance(environment, str) or environment not in _HOSTS):
        raise ReadOnlyBrokerError("Unsupported read-only endpoint or environment")
    if account_type not in ("INVEST", "STOCKS_ISA"):
        raise ReadOnlyBrokerError("Only declared Invest/Stocks ISA accounts are eligible")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 512 or
           any(ord(ch) < 33 or ord(ch) == 127 for ch in v)
           for v in (api_key, api_secret)) or ":" in api_key:
        raise ReadOnlyBrokerError("Invalid key pair shape")

    url = _HOSTS[environment] + _PATHS[endpoint]
    # Local receipt bounds are recorded by this process, not by the broker.
    # A monotonic interval remains meaningful if the wall clock is adjusted.
    receipt_started_wall = datetime.now(timezone.utc)
    receipt_started_at_utc = receipt_started_wall.isoformat()
    receipt_started_monotonic_ns = monotonic_ns()
    try:
        with httpx.Client(transport=transport, timeout=8.0, follow_redirects=False,
                          trust_env=False) as client:
            with client.stream("GET", url, auth=httpx.BasicAuth(api_key, api_secret),
                               headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                if response.status_code != 200:
                    raise ReadOnlyBrokerError("Broker read refused or unavailable")
                # Validate unambiguous wire framing before reading any payload.
                # The body is always decoded as strict UTF-8, regardless of
                # optional (matching) Content-Type charset metadata.
                size = _identity_json_wire_headers(response.headers)
                quota_observation = _rate_limit_observation(response.headers)
                # MockTransport may return an already-buffered Response; real
                # streamed responses are consumed as raw, undecoded bytes.
                if response.is_stream_consumed and transport is not None:
                    raw = response.content
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        raise ReadOnlyBrokerError("Broker response exceeds size limit")
                else:
                    chunks, total = [], 0
                    for chunk in response.iter_raw(chunk_size=65536):
                        total += len(chunk)
                        if total > _MAX_RESPONSE_BYTES:
                            raise ReadOnlyBrokerError("Broker response exceeds size limit")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
    except httpx.HTTPError:
        raise ReadOnlyBrokerError("Broker transport unavailable") from None
    receipt_elapsed_monotonic_ms = max(0, monotonic_ns() - receipt_started_monotonic_ns) / 1_000_000
    receipt_completed_wall = datetime.now(timezone.utc)
    receipt_completed_at_utc = receipt_completed_wall.isoformat()
    # Compare local wall-clock and monotonic elapsed time. This only detects
    # conspicuous local clock jumps; it cannot attest clock correctness.
    receipt_wall_elapsed_ms = (receipt_completed_wall - receipt_started_wall).total_seconds() * 1000
    receipt_clock_delta_ms = receipt_wall_elapsed_ms - receipt_elapsed_monotonic_ms
    receipt_clock_anomaly_detected = (receipt_wall_elapsed_ms < 0 or abs(receipt_clock_delta_ms) > 2000)
    http_time_observation = _http_time_header_observation(response.headers, receipt_completed_wall)

    # Content-Length, when present, describes the exact identity-encoded
    # response body. Reject a declared length that disagrees with the bytes
    # actually hashed and parsed, even if truncated JSON happens to be valid.
    # This is transport consistency only, not broker signing or entitlement.
    if size is not None and len(raw) != int(size):
        raise ReadOnlyBrokerError("Broker response length mismatch")

    try:
        # RFC 8259 interoperable JSON on the wire is UTF-8. Parsing bytes
        # directly would silently accept UTF-16/UTF-32 and UTF-8 BOMs; never
        # reinterpret malformed broker response bytes as a different charset.
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object_pairs,
                             parse_float=_finite_float, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ReadOnlyBrokerError("Invalid broker JSON") from None
    if not isinstance(payload, (dict, list)):
        raise ReadOnlyBrokerError("Unexpected broker JSON shape")
    try:
        _reject_unpaired_surrogates(payload)
    except ValueError:
        raise ReadOnlyBrokerError("Invalid broker JSON") from None
    return {
        "provider": "Trading 212", "environment": environment,
        "account_type_declared": account_type, "account_type_verified": False,
        "endpoint": endpoint, "received_at_utc": receipt_completed_at_utc,
        "receipt_started_at_utc": receipt_started_at_utc,
        "receipt_completed_at_utc": receipt_completed_at_utc,
        "receipt_elapsed_monotonic_ms": receipt_elapsed_monotonic_ms,
        "receipt_wall_elapsed_ms": receipt_wall_elapsed_ms,
        "receipt_wall_vs_monotonic_delta_ms": receipt_clock_delta_ms,
        "receipt_clock_anomaly_detected": receipt_clock_anomaly_detected,
        "receipt_clock_anomaly_threshold_ms": 2000,
        "receipt_clock_attested": False,
        "response_sha256": hashlib.sha256(raw).hexdigest(), "data": payload,
        "rate_limit_observation": quota_observation,
        "http_time_observation": http_time_observation,
        "server_clock_attested": False, "market_data_feed": False,
        "price_freshness_verified": False, "cfd_supported": False,
        "may_execute_order": False,
    }
