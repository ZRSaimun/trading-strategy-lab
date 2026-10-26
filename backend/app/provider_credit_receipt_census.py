"""Read-only Twelve Data reservation-to-receipt coverage; no vendor calls.

A caller-supplied receipt is NOT independently authenticated provider evidence.
No provider billing, account-wide quota, data-rights or trading claim is made.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
import re
import sqlite3
import time
from urllib.parse import quote

from .provider_credit_ledger_audit import (
    CreditLedgerAuditError, audit_provider_credit_ledger,
)

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REPORTS = 5000
_FALSE_FLAGS = (
    "provider_credit_quota_window_verified",
    "provider_account_credit_usage_reconciled",
    "source_authenticated", "provider_entitlement_verified",
    "retention_and_display_rights_verified", "expected_calendar_verified",
    "executable_bid_ask_verified", "live", "may_execute_order",
)


class CreditReceiptCensusError(ValueError):
    """Sanitized denial; never expose raw reports, paths or credentials."""


def _hash(value: object, pattern: re.Pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def audit_twelvedata_credit_receipt_coverage(
    db_path: str, *, utc_day: str, receipt_reports: list[dict],
) -> dict:
    """Match all local daily reservations to supplied one-shot receipt reports.

    Requires a quiescent private durable SQLite ledger. Unmatched reservations
    are uncertain attempts; never infer they can be refunded or retried.
    """
    if type(utc_day) is not str or len(utc_day) != 10:
        raise CreditReceiptCensusError("Invalid UTC day")
    try:
        if date.fromisoformat(utc_day).isoformat() != utc_day:
            raise ValueError()
    except ValueError:
        raise CreditReceiptCensusError("Invalid UTC day") from None
    if type(receipt_reports) is not list or len(receipt_reports) > _MAX_REPORTS:
        raise CreditReceiptCensusError("Bounded receipt report list required")
    try:
        before = audit_provider_credit_ledger(db_path, utc_day=utc_day)
        if before["status"] != "CONSISTENT_OFFLINE_ONLY":
            raise CreditReceiptCensusError("No audited daily budget policy")
        # Full ledger audit has checked schema, all rows, permissions, sidecars
        # and integrity. The two hashes bracket this immutable read.
        uri = "file:" + quote(db_path, safe="/") + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            rows = conn.execute(
                "SELECT request_id, manifest_sha256, reserved_at_utc "
                "FROM credit_reservation WHERE utc_day=? "
                "ORDER BY reserved_at_utc, request_id LIMIT ?",
                (utc_day, _MAX_REPORTS + 1),
            ).fetchall()
        if len(rows) != before["reserved_credits"] or len(rows) > _MAX_REPORTS:
            raise CreditReceiptCensusError("Ledger reservation population changed")
        reservations = {rid: (manifest, stamp) for rid, manifest, stamp in rows}
        if len(reservations) != len(rows):
            raise CreditReceiptCensusError("Duplicate ledger reservations")
        seen = set()
        observed_headers = missing_headers = 0
        now = int(time.time())
        for report in receipt_reports:
            if type(report) is not dict or len(report) > 100:
                raise CreditReceiptCensusError("Invalid bounded receipt report")
            rid = report.get("credit_budget_reservation_id")
            manifest = report.get("operator_manifest_sha256")
            if (not _hash(rid, _HEX32) or rid in seen or rid not in reservations
                    or not _hash(manifest, _HEX64)
                    or manifest != reservations[rid][0]
                    or not _hash(report.get("decoded_http_body_sha256"), _HEX64)
                    or not _hash(report.get("source_snapshot_sha256"), _HEX64)
                    or report.get("credit_budget_utc_day") != utc_day):
                raise CreditReceiptCensusError("Duplicate, unknown or mismatched receipt")
            seen.add(rid)
            start = report.get("server_request_started_at_utc")
            received = report.get("server_response_received_at_utc")
            elapsed_ms = report.get("server_request_elapsed_ms")
            if (type(start) is not int or type(received) is not int
                    or type(elapsed_ms) is not int
                    or not reservations[rid][1] <= start <= received <= now
                    or not 0 <= elapsed_ms <= 60_000
                    or received - start > 65
                    or abs((received - start) * 1000 - elapsed_ms) > 5_000):
                raise CreditReceiptCensusError("Invalid receipt timing evidence")
            if (report.get("protocol") != "one-shot-twelvedata-m1-observation-v1"
                    or report.get("source_endpoint") != "https://api.twelvedata.com/time_series"
                    or report.get("instrument_mapping") != "XAUUSD-TD -> XAU/USD"
                    or type(report.get("provider_http_status")) is not int
                    or report["provider_http_status"] != 200
                    or any(report.get(flag) is not False for flag in _FALSE_FLAGS)):
                raise CreditReceiptCensusError("Unapproved receipt identity or claim")
            status = report.get("provider_credit_header_status")
            used = report.get("provider_api_credits_used")
            left = report.get("provider_api_credits_left")
            if status == "MISSING_REVIEW_REQUIRED":
                if used is not None or left is not None:
                    raise CreditReceiptCensusError("Invalid absent credit headers")
                missing_headers += 1
            elif status == "OBSERVED_UNVERIFIED":
                if (type(used) is not int or type(left) is not int
                        or not 1 <= used <= 1_000_000_000
                        or not 0 <= left <= 1_000_000_000
                        or used + left > 1_000_000_000):
                    raise CreditReceiptCensusError("Invalid credit header counters")
                observed_headers += 1
            else:
                raise CreditReceiptCensusError("Invalid credit header status")
        after = audit_provider_credit_ledger(db_path, utc_day=utc_day)
        if before != after:
            raise CreditReceiptCensusError("Ledger changed during receipt census")
    except CreditReceiptCensusError:
        raise
    except (CreditLedgerAuditError, sqlite3.Error, OSError, TypeError, KeyError):
        raise CreditReceiptCensusError("Unable to verify quiescent local receipt census") from None

    missing = len(reservations) - len(seen)
    return {
        "status": ("LOCAL_COVERAGE_ONLY" if not missing and not missing_headers
                   else "REVIEW_REQUIRED"),
        "utc_day": utc_day,
        "audited_reservations": len(reservations),
        "matched_receipt_reports": len(seen),
        "reservations_without_receipt": missing,
        "observed_credit_header_pairs": observed_headers,
        "reports_missing_credit_headers": missing_headers,
        "ledger_sha256": before["ledger_sha256"],
        "read_only": True,
        "provider_account_credit_usage_reconciled": False,
        "provider_entitlement_verified": False,
        "source_authenticated": False,
        "market_data_live": False,
        "may_execute_order": False,
    }
