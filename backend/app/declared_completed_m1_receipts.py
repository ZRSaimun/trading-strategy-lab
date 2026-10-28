"""Offline, fail-closed census of *declared* completed M1 feed receipts.

No provider calls, credentials, data writes, licensing verification, broker
orders, or permission to label an unauthenticated observation as live.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

_MAX_ROWS = 5_000
_MAX_SECOND = 253402300799
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_PRICE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?\Z")
_FIELDS = frozenset({
    "event_id", "provider", "instrument", "source_id", "price_side",
    "minute_start_utc", "finalized_at_utc", "received_at_utc",
    "is_final", "open", "high", "low", "close",
})


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name}: bounded ASCII identity required")
    return value


def _second(value: object, name: str, *, minute: bool = False) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_SECOND:
        raise ValueError(f"{name}: valid UTC epoch second required")
    if minute and value % 60:
        raise ValueError(f"{name}: M1 start must be minute-aligned")
    return value


def _price(value: object, name: str) -> Decimal:
    if type(value) is not str or _PRICE.fullmatch(value) is None:
        raise ValueError(f"{name}: canonical positive decimal text required")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name}: invalid decimal") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{name}: price must be positive and finite")
    return number


def audit_declared_completed_m1_receipts(
    receipts: list[dict], *, provider: str, instrument: str, source_id: str,
    price_side: str, as_of_utc: int, max_age_seconds: int = 180,
    max_transport_lag_seconds: int = 30,
    expected_utc_minutes: list[int] | None = None,
) -> dict:
    """Check declared receipt consistency, not authenticity or session coverage.

    Timestamps must be UTC seconds. Candle starts are aligned to minutes.
    Source-provided finality and timestamps remain unauthenticated assertions.
    The optional expected-minute inventory is also caller-declared.
    """
    provider = _identifier(provider, "provider")
    instrument = _identifier(instrument, "instrument")
    source_id = _identifier(source_id, "source_id")
    if price_side not in ("mid", "bid", "ask"):
        raise ValueError("Explicit mid, bid or ask side required")
    now = _second(as_of_utc, "as_of_utc")
    if (type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600
            or type(max_transport_lag_seconds) is not int
            or not 0 <= max_transport_lag_seconds <= 300):
        raise ValueError("Bounded freshness and transport budgets required")
    if type(receipts) is not list or not 1 <= len(receipts) <= _MAX_ROWS:
        raise ValueError("Nonempty bounded receipt inventory required")
    if expected_utc_minutes is not None:
        if (type(expected_utc_minutes) is not list
                or len(expected_utc_minutes) > _MAX_ROWS):
            raise ValueError("Bounded expected-minute inventory required")
        previous = None
        for minute in expected_utc_minutes:
            _second(minute, "expected_utc_minutes", minute=True)
            if previous is not None and minute <= previous:
                raise ValueError("Expected minutes must be strictly increasing")
            previous = minute

    seen_ids: set[str] = set()
    seen_minutes: set[int] = set()
    previous_minute = previous_receipt = None
    duplicate_minutes = backward_minutes = observed_gap_minutes = 0
    lag_exceeded = 0
    digest = hashlib.sha256(b"DECLARED_COMPLETED_M1_RECEIPT_CENSUS_V1\n")
    digest.update(json.dumps(
        [provider, instrument, source_id, price_side],
        separators=(",", ":"), ensure_ascii=True
    ).encode("ascii") + b"\n")
    newest_start = newest_received = None
    for index, record in enumerate(receipts):
        if type(record) is not dict or set(record) != _FIELDS:
            raise ValueError(f"receipt {index}: exact schema required")
        event_id = _identifier(record["event_id"], "event_id")
        if event_id in seen_ids:
            raise ValueError("Duplicate source event ID")
        seen_ids.add(event_id)
        if any(record[key] != value for key, value in (
            ("provider", provider), ("instrument", instrument),
            ("source_id", source_id), ("price_side", price_side)
        )):
            raise ValueError("Mixed provider/instrument/source/price-side receipts")
        start = _second(record["minute_start_utc"], "minute_start_utc", minute=True)
        finalized = _second(record["finalized_at_utc"], "finalized_at_utc")
        received = _second(record["received_at_utc"], "received_at_utc")
        if type(record["is_final"]) is not bool or not record["is_final"]:
            raise ValueError("Only explicitly finalized candles are accepted")
        if not start + 60 <= finalized <= received <= now:
            raise ValueError("Candle finality/receipt/as-of chronology invalid")
        if previous_receipt is not None and received < previous_receipt:
            raise ValueError("Receipt ingestion timestamps moved backward")
        prices = [_price(record[k], k) for k in ("open", "high", "low", "close")]
        opening, high, low, closing = prices
        if low > min(opening, closing) or high < max(opening, closing):
            raise ValueError("Invalid OHLC ordering")
        if start in seen_minutes:
            duplicate_minutes += 1
        seen_minutes.add(start)
        if previous_minute is not None:
            if start < previous_minute:
                backward_minutes += 1
            elif start > previous_minute + 60:
                observed_gap_minutes += (start - previous_minute) // 60 - 1
        if received - finalized > max_transport_lag_seconds:
            lag_exceeded += 1
        digest.update(json.dumps(
            [event_id, start, finalized, received, record["open"],
             record["high"], record["low"], record["close"]],
            separators=(",", ":"), ensure_ascii=True
        ).encode("ascii") + b"\n")
        previous_minute, previous_receipt = start, received
        if newest_start is None or start > newest_start:
            newest_start, newest_received = start, received

    expected = set(expected_utc_minutes) if expected_utc_minutes is not None else None
    missing = len(expected - seen_minutes) if expected is not None else None
    extra = len(seen_minutes - expected) if expected is not None else None
    latest_candle_age = now - (newest_start + 60)
    latest_receipt_age = now - newest_received
    structurally_clean = (
        duplicate_minutes == 0 and backward_minutes == 0
        and lag_exceeded == 0 and (missing in (None, 0))
        and (extra in (None, 0))
    )
    return {
        "protocol": "declared-completed-m1-receipt-preflight-v1",
        "provider": provider, "instrument": instrument,
        "source_id": source_id, "price_side": price_side,
        "receipt_rows": len(receipts), "distinct_minutes": len(seen_minutes),
        "duplicate_minute_rows": duplicate_minutes,
        "backward_candle_events": backward_minutes,
        "observed_gap_minutes_not_proven_missing": observed_gap_minutes,
        "transport_lag_exceeded_rows": lag_exceeded,
        "expected_inventory_supplied": expected is not None,
        "missing_declared_expected_minutes": missing,
        "extra_minutes_outside_declared_expected": extra,
        "latest_candle_end_age_seconds": latest_candle_age,
        "latest_receipt_age_seconds": latest_receipt_age,
        "declared_freshness_within_budget": (
            latest_candle_age <= max_age_seconds
            and latest_receipt_age <= max_age_seconds
            and lag_exceeded == 0
        ),
        "structurally_clean": structurally_clean,
        "receipt_inventory_sha256": digest.hexdigest(),
        "source_authenticity_verified": False,
        "server_owned_receipt_clock_verified": False,
        "licensing_verified": False,
        "session_calendar_verified": False,
        "market_data_live": False,
        "research_ready": False,
        "may_execute_order": False,
    }
