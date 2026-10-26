"""Opt-in Trading 212 Invest/ISA read-only REST client; not a market-data feed.

No background requests, persistence, order endpoints, or CFD support. Caller owns
credentials, account eligibility, permissions and any data usage rights.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

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
    try:
        with httpx.Client(transport=transport, timeout=8.0, follow_redirects=False,
                          trust_env=False) as client:
            with client.stream("GET", url, auth=httpx.BasicAuth(api_key, api_secret),
                               headers={"Accept": "application/json"}) as response:
                if response.status_code != 200:
                    raise ReadOnlyBrokerError("Broker read refused or unavailable")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ReadOnlyBrokerError("Unexpected broker response content type")
                size = response.headers.get("content-length")
                if size is not None and (not size.isascii() or not size.isdecimal()
                                         or len(size) > 8 or int(size) > _MAX_RESPONSE_BYTES):
                    raise ReadOnlyBrokerError("Broker response exceeds size limit")
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        raise ReadOnlyBrokerError("Broker response exceeds size limit")
                    chunks.append(chunk)
                raw = b"".join(chunks)
    except httpx.HTTPError:
        raise ReadOnlyBrokerError("Broker transport unavailable") from None

    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ReadOnlyBrokerError("Invalid broker JSON") from None
    if not isinstance(payload, (dict, list)):
        raise ReadOnlyBrokerError("Unexpected broker JSON shape")
    return {
        "provider": "Trading 212", "environment": environment,
        "account_type_declared": account_type, "account_type_verified": False,
        "endpoint": endpoint, "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "response_sha256": hashlib.sha256(raw).hexdigest(), "data": payload,
        "server_clock_attested": False, "market_data_feed": False,
        "price_freshness_verified": False, "cfd_supported": False,
        "may_execute_order": False,
    }
