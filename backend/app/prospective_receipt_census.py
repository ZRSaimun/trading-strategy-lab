"""Offline, fail-closed census for *declared* prospective completed M1 receipts.

No network, persistence, entitlement verification, session inference, broker quotes,
execution, or live-feed status. All timestamps and identity are caller-declared.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,79}\Z")
_FIELDS = frozenset({"provider", "symbol", "venue", "price_side", "bar_start_utc",
                     "received_at_utc", "open", "high", "low", "close"})


def _utc(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def audit_declared_m1_receipts(
    receipts: list[dict], expected_minutes: list[int], *, provider: str,
    symbol: str, venue: str, price_side: str, observed_at_utc: int,
    max_receipt_lag_seconds: int = 120, max_observation_age_seconds: int = 180,
    sample_limit: int = 10,
) -> dict:
    """Compare received completed bars against an explicit UTC minute census.

    The caller MUST supply expected minutes from a separately justified calendar;
    no inference about sessions or feed entitlements is made. The output is never
    a license, authenticity, executable-price, or live-data attestation.
    """
    identity = (provider, symbol, venue, price_side)
    if any(not isinstance(x, str) or not _ID.fullmatch(x) for x in identity):
        raise ValueError("Exact bounded source identity required")
    if price_side not in ("BID", "ASK", "MID", "TRADE", "UNSPECIFIED"):
        raise ValueError("Unsupported price side; no substitution")
    if (type(observed_at_utc) is not int or not 60 <= observed_at_utc <= 253402300799
            or type(max_receipt_lag_seconds) is not int or max_receipt_lag_seconds < 0
            or type(max_observation_age_seconds) is not int or max_observation_age_seconds < 0
            or type(sample_limit) is not int or not 0 <= sample_limit <= 50):
        raise ValueError("Invalid observation time or resource limits")
    if (not isinstance(receipts, list) or len(receipts) > 10_000
            or not isinstance(expected_minutes, list) or not 1 <= len(expected_minutes) <= 10_000):
        raise ValueError("Bounded receipts and nonempty expected census required")
    previous = -1
    for t in expected_minutes:
        if (type(t) is not int or t < 0 or t % 60 or t <= previous
                or t + 60 > observed_at_utc):
            raise ValueError("Expected UTC minutes must be unique, ordered and completed")
        previous = t

    seen: dict[int, tuple] = {}
    duplicate_rows = conflicting_duplicate_rows = late_receipts = 0
    latest_receipt = None
    max_lag = 0
    for row in receipts:
        if not isinstance(row, dict) or row.keys() != _FIELDS:
            raise ValueError("Receipt must contain exactly the declared fields")
        if tuple(row[k] for k in ("provider", "symbol", "venue", "price_side")) != identity:
            raise ValueError("Mixed source identity or price side")
        t, received = row["bar_start_utc"], row["received_at_utc"]
        if (type(t) is not int or t < 0 or t % 60 or type(received) is not int
                or t + 60 > received or received > observed_at_utc):
            raise ValueError("Future, incomplete, or impossible receipt chronology")
        ohlc = tuple(row[k] for k in ("open", "high", "low", "close"))
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in ohlc):
            raise ValueError("Nonfinite or nonnumeric OHLC")
        opening, high, low, close = ohlc
        if low > min(opening, close) or high < max(opening, close) or low > high:
            raise ValueError("Inconsistent OHLC bounds")
        if t in seen:
            duplicate_rows += 1
            if seen[t] != ohlc:
                conflicting_duplicate_rows += 1
        else:
            seen[t] = ohlc
        lag = received - (t + 60)
        late_receipts += lag > max_receipt_lag_seconds
        max_lag = max(max_lag, lag)
        latest_receipt = received if latest_receipt is None else max(latest_receipt, received)

    expected = set(expected_minutes)
    observed = set(seen)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    stale = latest_receipt is None or observed_at_utc - latest_receipt > max_observation_age_seconds
    incomplete = bool(missing or unexpected or duplicate_rows or late_receipts or stale)
    fingerprint_input = {
        "identity": identity, "observed_at_utc": observed_at_utc,
        "expected_minutes": expected_minutes,
        "receipts": receipts,
        "max_receipt_lag_seconds": max_receipt_lag_seconds,
        "max_observation_age_seconds": max_observation_age_seconds,
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True,
                                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {
        "protocol": "declared-completed-m1-receipt-census-v1",
        "status": "REVIEW_REQUIRED" if incomplete else "INTERNAL_CENSUS_ONLY_NOT_LIVE",
        "source": {"provider": provider, "symbol": symbol, "venue": venue,
                   "price_side": price_side},
        "input_sha256": fingerprint,
        "expected_minutes": len(expected), "receipt_rows": len(receipts),
        "unique_observed_minutes": len(observed),
        "missing_expected_minutes": len(missing),
        "unexpected_observed_minutes": len(unexpected),
        "duplicate_receipt_rows": duplicate_rows,
        "conflicting_duplicate_rows": conflicting_duplicate_rows,
        "late_receipt_rows": late_receipts,
        "max_declared_receipt_lag_seconds": max_lag if receipts else None,
        "seconds_since_last_declared_receipt": (
            observed_at_utc - latest_receipt if latest_receipt is not None else None),
        "stale_declared_observation": stale,
        "missing_utc_samples": [_utc(t) for t in missing[:sample_limit]],
        "unexpected_utc_samples": [_utc(t) for t in unexpected[:sample_limit]],
        "sample_limit": sample_limit,
        "expected_calendar_verified": False,
        "server_receipt_clock_attested": False,
        "source_authenticated": False,
        "provider_entitlement_verified": False,
        "retention_and_display_rights_verified": False,
        "executable_bid_ask_verified": False,
        "live": False, "may_execute_order": False,
        "caveat": "Caller-declared receipts and expected UTC minutes only; no vendor attestation, session proof, live status or trade permission.",
    }
