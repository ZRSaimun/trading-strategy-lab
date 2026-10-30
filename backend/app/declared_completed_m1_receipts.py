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
    max_finalization_lag_seconds: int = 60,
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
            or not 0 <= max_transport_lag_seconds <= 300
            or type(max_finalization_lag_seconds) is not int
            or not 0 <= max_finalization_lag_seconds <= 300):
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
    # Keep only bounded first-observation OHLC text per minute for revision census.
    first_minute_ohlc: dict[int, tuple[str, str, str, str]] = {}
    previous_minute = previous_receipt = None
    duplicate_minutes = backward_minutes = observed_gap_minutes = 0
    changed_duplicate_ohlc_text_rows = changed_duplicate_numeric_ohlc_rows = 0
    lag_exceeded = finalization_lag_exceeded = 0
    # A received-after-budget row is not proof of a provider outage. A
    # first-seen minute below the high-water mark is an out-of-order backfill,
    # even when its immediate predecessor was also an older minute.
    after_budget_rows = 0
    after_budget_minutes: set[int] = set()
    # Late duplicate revisions must not be mistaken for late first issuance.
    first_seen_after_budget_minutes: set[int] = set()
    late_first_seen_backfill_minutes: set[int] = set()
    out_of_order_first_seen_minutes: set[int] = set()
    high_water_start = None
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
        raw_ohlc = tuple(record[k] for k in ("open", "high", "low", "close"))
        first_seen = start not in seen_minutes
        first_seen_backfill = (
            first_seen and high_water_start is not None
            and start < high_water_start
        )
        if first_seen_backfill:
            out_of_order_first_seen_minutes.add(start)
        if high_water_start is None or start > high_water_start:
            high_water_start = start
        if start in seen_minutes:
            duplicate_minutes += 1
            original_ohlc = first_minute_ohlc[start]
            if raw_ohlc != original_ohlc:
                changed_duplicate_ohlc_text_rows += 1
                # Distinguish a numerical price revision from text-only scale
                # changes such as 100.0 versus 100.00. Both remain quarantined.
                if any(value != Decimal(first)
                       for value, first in zip(prices, original_ohlc)):
                    changed_duplicate_numeric_ohlc_rows += 1
        else:
            first_minute_ohlc[start] = raw_ohlc
        seen_minutes.add(start)
        if previous_minute is not None:
            if start < previous_minute:
                backward_minutes += 1
            elif start > previous_minute + 60:
                observed_gap_minutes += (start - previous_minute) // 60 - 1
        if received - finalized > max_transport_lag_seconds:
            lag_exceeded += 1
        # A provider can finalize a long-stale bar immediately before delivery.
        # Transport lag alone cannot establish prompt candle finalization.
        if finalized - (start + 60) > max_finalization_lag_seconds:
            finalization_lag_exceeded += 1
        # This composite arrival deadline is a *declared* diagnostic only.
        # Individual stage breaches above remain independently quarantined,
        # including at an exact composite-deadline boundary.
        if received > (start + 60 + max_finalization_lag_seconds
                       + max_transport_lag_seconds):
            after_budget_rows += 1
            after_budget_minutes.add(start)
            if first_seen:
                first_seen_after_budget_minutes.add(start)
                if first_seen_backfill:
                    late_first_seen_backfill_minutes.add(start)
        digest.update(json.dumps(
            [event_id, start, finalized, received, record["open"],
             record["high"], record["low"], record["close"]],
            separators=(",", ":"), ensure_ascii=True
        ).encode("ascii") + b"\n")
        previous_minute, previous_receipt = start, received
        if newest_start is None or start > newest_start:
            newest_start, newest_received = start, received

    # A receipt-only checksum intentionally does not bind the as-of clock,
    # freshness budgets or expected-session inventory. Keep a distinct,
    # domain-separated policy fingerprint so two otherwise identical receipt
    # populations cannot be mistaken for the same audit decision.
    policy_digest = hashlib.sha256(b"DECLARED_COMPLETED_M1_AUDIT_POLICY_V1\n")
    policy_digest.update(json.dumps(
        [provider, instrument, source_id, price_side, now, max_age_seconds,
         max_transport_lag_seconds, max_finalization_lag_seconds,
         expected_utc_minutes],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii") + b"\n")

    expected = set(expected_utc_minutes) if expected_utc_minutes is not None else None
    missing_minutes = sorted(expected - seen_minutes) if expected is not None else None
    extra_minutes = sorted(seen_minutes - expected) if expected is not None else None
    missing = len(missing_minutes) if missing_minutes is not None else None
    extra = len(extra_minutes) if extra_minutes is not None else None
    # Only adjacent declared expected UTC minutes belong to the same missing
    # run. Non-session intervals omitted by the caller break the run.
    missing_runs = longest_missing_run = None
    if missing_minutes is not None:
        missing_runs = 0
        longest_missing_run = 0
        run_length = 0
        previous_missing = None
        for minute in missing_minutes:
            if previous_missing is None or minute != previous_missing + 60:
                missing_runs += 1
                run_length = 1
            else:
                run_length += 1
            longest_missing_run = max(longest_missing_run, run_length)
            previous_missing = minute
    # An expected minute may still be inside its declared finalization and
    # transport budgets. Separate such pending gaps from overdue declarations
    # without treating either as authenticated missed provider issuance.
    overdue_missing = pending_missing = overdue_sample = None
    overdue_runs = longest_overdue_run = pending_sample = None
    if missing_minutes is not None:
        overdue_minutes = [
            minute for minute in missing_minutes
            if now > (minute + 60 + max_finalization_lag_seconds
                      + max_transport_lag_seconds)
        ]
        overdue_missing = len(overdue_minutes)
        pending_missing = len(missing_minutes) - overdue_missing
        overdue_sample = overdue_minutes[:12]
        pending_sample = missing_minutes[overdue_missing:overdue_missing + 12]
        # Deadline increases strictly with the expected minute start, so
        # overdue identities are a sorted prefix. An omitted session minute
        # splits a run rather than fabricating continuous market coverage.
        overdue_runs = longest_overdue_run = 0
        previous_overdue = None
        current_run = 0
        for minute in overdue_minutes:
            if previous_overdue is None or minute != previous_overdue + 60:
                overdue_runs += 1
                current_run = 1
            else:
                current_run += 1
            longest_overdue_run = max(longest_overdue_run, current_run)
            previous_overdue = minute
    # A source-order forward jump is not a unique missing-minute census:
    # delayed backfills and replayed ranges can inflate that observation.
    # Count interior holes once across distinct UTC minute identities. These
    # may still be market closures, not verified provider outages.
    ordered_minutes = sorted(seen_minutes)
    interior_gap_lengths = [
        (right - left) // 60 - 1
        for left, right in zip(ordered_minutes, ordered_minutes[1:])
        if right > left + 60
    ]
    distinct_interior_unobserved_minutes = sum(interior_gap_lengths)
    distinct_interior_gap_runs = len(interior_gap_lengths)
    largest_interior_gap_run = max(interior_gap_lengths, default=0)
    latest_candle_age = now - (newest_start + 60)
    latest_receipt_age = now - newest_received
    structurally_clean = (
        duplicate_minutes == 0 and backward_minutes == 0
        and lag_exceeded == 0 and finalization_lag_exceeded == 0
        and (missing in (None, 0))
        and (extra in (None, 0))
    )
    return {
        "protocol": "declared-completed-m1-receipt-preflight-v1",
        "provider": provider, "instrument": instrument,
        "source_id": source_id, "price_side": price_side,
        "receipt_rows": len(receipts), "distinct_minutes": len(seen_minutes),
        "duplicate_minute_rows": duplicate_minutes,
        "changed_duplicate_ohlc_text_rows": changed_duplicate_ohlc_text_rows,
        "changed_duplicate_numeric_ohlc_rows": changed_duplicate_numeric_ohlc_rows,
        "backward_candle_events": backward_minutes,
        "out_of_order_first_seen_minutes": len(out_of_order_first_seen_minutes),
        "out_of_order_first_seen_minute_sample_utc": sorted(
            out_of_order_first_seen_minutes
        )[:12],
        "declared_arrived_after_budget_rows": after_budget_rows,
        "declared_arrived_after_budget_distinct_minutes": len(after_budget_minutes),
        "declared_arrived_after_budget_minute_sample_utc": sorted(
            after_budget_minutes
        )[:12],
        "declared_first_seen_after_budget_minutes": len(
            first_seen_after_budget_minutes
        ),
        "declared_first_seen_after_budget_minute_sample_utc": sorted(
            first_seen_after_budget_minutes
        )[:12],
        "declared_late_first_seen_backfill_minutes": len(
            late_first_seen_backfill_minutes
        ),
        "declared_late_first_seen_backfill_minute_sample_utc": sorted(
            late_first_seen_backfill_minutes
        )[:12],
        "observed_gap_minutes_not_proven_missing": observed_gap_minutes,
        "distinct_interior_unobserved_minutes_not_proven_missing": (
            distinct_interior_unobserved_minutes
        ),
        "distinct_interior_gap_runs_not_proven_missing": distinct_interior_gap_runs,
        "largest_interior_gap_run_minutes_not_proven_missing": (
            largest_interior_gap_run
        ),
        "transport_lag_exceeded_rows": lag_exceeded,
        "finalization_lag_exceeded_rows": finalization_lag_exceeded,
        "declared_max_finalization_lag_seconds": max_finalization_lag_seconds,
        "expected_inventory_supplied": expected is not None,
        "missing_declared_expected_minutes": missing,
        "extra_minutes_outside_declared_expected": extra,
        "declared_missing_expected_gap_runs": missing_runs,
        "largest_declared_missing_expected_gap_run_minutes": longest_missing_run,
        "missing_declared_expected_minute_sample_utc": (
            missing_minutes[:12] if missing_minutes is not None else None
        ),
        "extra_declared_expected_minute_sample_utc": (
            extra_minutes[:12] if extra_minutes is not None else None
        ),
        "declared_overdue_missing_expected_minutes": overdue_missing,
        "declared_pending_missing_expected_minutes": pending_missing,
        "overdue_declared_expected_minute_sample_utc": overdue_sample,
        "pending_declared_expected_minute_sample_utc": pending_sample,
        "declared_overdue_missing_expected_gap_runs": overdue_runs,
        "largest_declared_overdue_missing_expected_gap_run_minutes": (
            longest_overdue_run
        ),
        "latest_candle_end_age_seconds": latest_candle_age,
        "latest_receipt_age_seconds": latest_receipt_age,
        "declared_freshness_within_budget": (
            latest_candle_age <= max_age_seconds
            and latest_receipt_age <= max_age_seconds
            and lag_exceeded == 0
            and finalization_lag_exceeded == 0
        ),
        "structurally_clean": structurally_clean,
        "receipt_inventory_sha256": digest.hexdigest(),
        "declared_audit_policy_sha256": policy_digest.hexdigest(),
        "source_authenticity_verified": False,
        "server_owned_receipt_clock_verified": False,
        "licensing_verified": False,
        "session_calendar_verified": False,
        "market_data_live": False,
        "research_ready": False,
        "may_execute_order": False,
    }
