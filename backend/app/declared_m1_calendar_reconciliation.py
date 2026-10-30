"""Read-only reconciliation against an explicitly declared UTC M1 inventory.

A caller-supplied expected-minute list is NOT an authenticated market calendar.
This module makes no provider requests, changes no candles and cannot certify
missing market data, licensing, feed freshness or executable quotes.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

MAX_MINUTES = 100_000
MAX_UTC_MINUTE = 253402300740  # 9999-12-31 23:59:00 UTC


def _minutes(value: object, label: str, *, allow_empty: bool) -> list[int]:
    if type(value) is not list or len(value) > MAX_MINUTES or (not allow_empty and not value):
        raise ValueError(f"{label} must be a bounded UTC M1 list")
    previous = -1
    for minute in value:
        if (type(minute) is not int or minute < 0 or minute > MAX_UTC_MINUTE
                or minute % 60 or minute <= previous):
            raise ValueError(f"{label} must contain strictly increasing UTC minute epochs")
        previous = minute
    return value


def _iso(minute: int) -> str:
    return datetime.fromtimestamp(minute, timezone.utc).isoformat()


def _digest(minutes: list[int]) -> str:
    # A deterministic local fingerprint of the *declared list*, not a signature
    # from the calendar publisher, exchange or provider.
    payload = "UTC_M1_V1\n" + "".join(f"{minute}\n" for minute in minutes)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def audit_declared_m1_coverage(
    observed_minutes: list[int],
    expected_minutes: list[int],
    *,
    declaration_id: str,
    sample_limit: int = 5,
) -> dict:
    """Compare two sorted timestamp inventories without inventing market sessions.

    Missing means absent from the caller's *declared* expected inventory only.
    A verified independent session/DST/holiday calendar and licensing review
    are separate requirements before calling any gap a market-data outage.
    """
    if (type(declaration_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", declaration_id) is None):
        raise ValueError("A bounded nonempty declaration identifier is required")
    if type(sample_limit) is not int or not 0 <= sample_limit <= 20:
        raise ValueError("sample_limit must be an integer from 0 to 20")
    observed = _minutes(observed_minutes, "observed_minutes", allow_empty=True)
    expected = _minutes(expected_minutes, "expected_minutes", allow_empty=False)

    i = j = matched = missing = outside = 0
    missing_sample: list[str] = []
    outside_sample: list[str] = []
    # Runs require adjacent *declared* missing minutes in UTC, not simply
    # consecutive positions in a possibly discontinuous session inventory.
    missing_runs = longest_missing_run = current_missing_run = 0
    previous_missing_minute: int | None = None
    missing_run_samples: list[dict] = []
    while i < len(expected) or j < len(observed):
        if j == len(observed) or (i < len(expected) and expected[i] < observed[j]):
            minute = expected[i]
            missing += 1
            if previous_missing_minute is None or minute != previous_missing_minute + 60:
                missing_runs += 1
                current_missing_run = 0
                if len(missing_run_samples) < sample_limit:
                    missing_run_samples.append({
                        "first_utc": _iso(minute), "last_utc": _iso(minute),
                        "minutes": 0,
                    })
            current_missing_run += 1
            longest_missing_run = max(longest_missing_run, current_missing_run)
            previous_missing_minute = minute
            if missing_runs <= sample_limit:
                missing_run_samples[-1]["last_utc"] = _iso(minute)
                missing_run_samples[-1]["minutes"] = current_missing_run
            if len(missing_sample) < sample_limit:
                missing_sample.append(_iso(minute))
            i += 1
        elif i == len(expected) or observed[j] < expected[i]:
            outside += 1
            if len(outside_sample) < sample_limit:
                outside_sample.append(_iso(observed[j]))
            j += 1
        else:
            matched += 1
            i += 1
            j += 1

    return {
        "assessment": "DECLARED_EXPECTED_M1_ONLY",
        "declaration_id": declaration_id,
        "declared_inventory_sha256": _digest(expected),
        "observed_inventory_sha256": _digest(observed),
        "hash_scope": "canonical UTC minute epoch list, not provider bytes or source signature",
        "expected_minutes": len(expected),
        "observed_minutes": len(observed),
        "matched_declared_minutes": matched,
        "unobserved_declared_minutes": missing,
        "unobserved_declared_runs": missing_runs,
        "longest_unobserved_declared_run_minutes": longest_missing_run,
        "unobserved_declared_run_samples_utc": missing_run_samples,
        "observed_undeclared_minutes": outside,
        "declared_first_utc": _iso(expected[0]),
        "declared_last_utc": _iso(expected[-1]),
        "unobserved_declared_samples_utc": missing_sample,
        "observed_undeclared_samples_utc": outside_sample,
        "independent_calendar_verified": False,
        "provider_entitlement_verified": False,
        "source_authenticity_verified": False,
        "quote_side_verified": False,
        "missing_market_data_proven": False,
        "live": False,
        "may_execute_order": False,
        "caveat": "Declared expected minutes may omit or invent sessions, holidays and DST transitions; reconcile only against independently verified licensed calendar evidence.",
    }
