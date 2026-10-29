"""Opt-in Trading 212 Invest/ISA read-only REST client; not a market-data feed.

No background requests, persistence, order endpoints, or CFD support. Caller owns
credentials, account eligibility, permissions and any data usage rights.
"""
from __future__ import annotations

from datetime import datetime, timezone
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


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonstandard JSON constant")



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
    receipt_started_at_utc = datetime.now(timezone.utc).isoformat()
    receipt_started_monotonic_ns = monotonic_ns()
    try:
        with httpx.Client(transport=transport, timeout=8.0, follow_redirects=False,
                          trust_env=False) as client:
            with client.stream("GET", url, auth=httpx.BasicAuth(api_key, api_secret),
                               headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                if response.status_code != 200:
                    raise ReadOnlyBrokerError("Broker read refused or unavailable")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ReadOnlyBrokerError("Unexpected broker response content type")
                quota_observation = _rate_limit_observation(response.headers)
                # Never let an automatic decompressor allocate an unbounded chunk.
                if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                    raise ReadOnlyBrokerError("Compressed broker responses not supported")
                size = response.headers.get("content-length")
                if size is not None and (not size.isascii() or not size.isdecimal()
                                         or len(size) > 8 or int(size) > _MAX_RESPONSE_BYTES):
                    raise ReadOnlyBrokerError("Broker response exceeds size limit")
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
    receipt_completed_at_utc = datetime.now(timezone.utc).isoformat()

    # Content-Length, when present, describes the exact identity-encoded
    # response body. Reject a declared length that disagrees with the bytes
    # actually hashed and parsed, even if truncated JSON happens to be valid.
    # This is transport consistency only, not broker signing or entitlement.
    if size is not None and len(raw) != int(size):
        raise ReadOnlyBrokerError("Broker response length mismatch")

    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object_pairs,
                             parse_float=_finite_float, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ReadOnlyBrokerError("Invalid broker JSON") from None
    if not isinstance(payload, (dict, list)):
        raise ReadOnlyBrokerError("Unexpected broker JSON shape")
    return {
        "provider": "Trading 212", "environment": environment,
        "account_type_declared": account_type, "account_type_verified": False,
        "endpoint": endpoint, "received_at_utc": receipt_completed_at_utc,
        "receipt_started_at_utc": receipt_started_at_utc,
        "receipt_completed_at_utc": receipt_completed_at_utc,
        "receipt_elapsed_monotonic_ms": receipt_elapsed_monotonic_ms,
        "receipt_clock_attested": False,
        "response_sha256": hashlib.sha256(raw).hexdigest(), "data": payload,
        "rate_limit_observation": quota_observation,
        "server_clock_attested": False, "market_data_feed": False,
        "price_freshness_verified": False, "cfd_supported": False,
        "may_execute_order": False,
    }
