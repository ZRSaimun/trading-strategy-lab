"""Disconnected, bounded consistency review of caller-supplied Twelve Data credit headers.

This is NOT provider account reconciliation. Quota-window boundaries and all
receipts are supplied by the caller; resets, other keys, cached responses and
missing attempts cannot be independently excluded. No network or disk I/O.
"""
from __future__ import annotations

import re
import time

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_MAX_REPORTS = 5000
_MAX_CREDITS = 1_000_000_000
_FALSE_FLAGS = (
    "provider_credit_quota_window_verified",
    "provider_account_credit_usage_reconciled",
    "source_authenticated", "provider_entitlement_verified",
    "retention_and_display_rights_verified", "expected_calendar_verified",
    "executable_bid_ask_verified", "live", "may_execute_order",
)


class CreditHeaderSequenceError(ValueError):
    """Sanitized input denial; never echo caller evidence or credentials."""


def audit_twelvedata_credit_header_sequence(
    receipt_reports: list[dict], *,
    declared_window_start_utc: int, declared_window_end_utc: int,
) -> dict:
    """Flag inconsistent credit counters inside one *operator-declared* window.

    A clean result only says that a caller-selected, self-attested sequence is
    arithmetically consistent. It never asserts account-wide usage, actual
    quota-window boundaries, source authenticity or that no calls are missing.
    """
    now = int(time.time())
    if (type(declared_window_start_utc) is not int
            or type(declared_window_end_utc) is not int
            or not 60 <= declared_window_start_utc < declared_window_end_utc <= now
            or declared_window_end_utc - declared_window_start_utc > 86_400):
        raise CreditHeaderSequenceError("Invalid declared quota window")
    if type(receipt_reports) is not list or len(receipt_reports) > _MAX_REPORTS:
        raise CreditHeaderSequenceError("Bounded receipt list required")

    observations = []
    seen = set()
    missing_headers = 0
    for report in receipt_reports:
        if type(report) is not dict or len(report) > 100:
            raise CreditHeaderSequenceError("Invalid receipt report")
        rid = report.get("credit_budget_reservation_id")
        start = report.get("server_request_started_at_utc")
        received = report.get("server_response_received_at_utc")
        if (type(rid) is not str or _HEX32.fullmatch(rid) is None
                or rid in seen or type(start) is not int
                or type(received) is not int
                or not declared_window_start_utc <= start <= received <= declared_window_end_utc
                or report.get("protocol") != "one-shot-twelvedata-m1-observation-v1"
                or report.get("source_endpoint") != "https://api.twelvedata.com/time_series"
                or report.get("instrument_mapping") != "XAUUSD-TD -> XAU/USD"
                or type(report.get("provider_http_status")) is not int
                or report["provider_http_status"] != 200
                or any(report.get(flag) is not False for flag in _FALSE_FLAGS)):
            raise CreditHeaderSequenceError("Invalid receipt identity, time or claims")
        seen.add(rid)
        status = report.get("provider_credit_header_status")
        used = report.get("provider_api_credits_used")
        left = report.get("provider_api_credits_left")
        if status == "MISSING_REVIEW_REQUIRED":
            if used is not None or left is not None:
                raise CreditHeaderSequenceError("Invalid missing header pair")
            missing_headers += 1
        elif status == "OBSERVED_UNVERIFIED":
            if (type(used) is not int or type(left) is not int
                    or not 1 <= used <= _MAX_CREDITS
                    or not 0 <= left <= _MAX_CREDITS
                    or used + left > _MAX_CREDITS):
                raise CreditHeaderSequenceError("Invalid observed header pair")
        else:
            raise CreditHeaderSequenceError("Invalid header evidence status")
        observations.append((received, rid, used, left))

    observations.sort()
    contradictory = 0
    unexplained = 0
    compared = 0
    # Never compare across a missing receipt/header or tied response timestamp.
    # This also prevents a partial sequence from being described as complete.
    for previous, current in zip(observations, observations[1:]):
        t0, _, u0, l0 = previous
        t1, _, u1, l1 = current
        if None in (u0, l0, u1, l1) or t0 == t1:
            continue
        compared += 1
        if u0 + l0 != u1 + l1 or u1 < u0 or l1 > l0:
            contradictory += 1
        elif u1 - u0 != 1:
            # A non-unit increase might reflect other account clients,
            # provider caching, a reset, or omitted caller receipts.
            unexplained += 1
    tied_times = len(observations) - len({x[0] for x in observations})
    review = (len(observations) < 2 or missing_headers > 0
              or contradictory > 0 or unexplained > 0 or tied_times > 0
              or compared != len(observations) - 1)
    return {
        "status": "REVIEW_REQUIRED" if review else "SELF_ATTESTED_SEQUENCE_ONLY",
        "declared_window_start_utc": declared_window_start_utc,
        "declared_window_end_utc": declared_window_end_utc,
        "receipt_reports": len(observations),
        "compared_adjacent_pairs": compared,
        "reports_missing_credit_headers": missing_headers,
        "contradictory_counter_pairs": contradictory,
        "unexplained_credit_deltas": unexplained,
        "ambiguous_response_timestamp_pairs": tied_times,
        "declared_window_independently_verified": False,
        "provider_account_credit_usage_reconciled": False,
        "receipt_population_complete": False,
        "provider_entitlement_verified": False,
        "source_authenticated": False,
        "market_data_live": False,
        "may_execute_order": False,
        "read_only": True,
    }
