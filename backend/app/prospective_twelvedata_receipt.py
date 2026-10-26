"""Explicit one-shot Twelve Data M1 receipt review, never a live/order feed.

No routes, scheduler, persistence, subscriptions, or implicit provider calls.
The caller must separately establish rights and an independently sourced calendar.
"""
from __future__ import annotations

import hashlib
import math
import re
from time import monotonic as _monotonic, time as _wall_clock

from .expected_bar_manifest import (
    ExpectedM1Manifest, audit_m1_receipts_against_manifest,
    compile_expected_m1_manifest,
)
from .provider_snapshot import verify_normalized_snapshot
from .provider_credit_budget import CreditBudgetError, reserve_one_credit
from .providers.twelvedata import ProviderError, retrieve

_IDENTITY = ("twelvedata", "XAU/USD", "UNVERIFIED", "UNSPECIFIED")
_MAX_EXPECTED = 5000


class ProspectiveReceiptError(ValueError):
    """Sanitized refusal, never a provider response or credential."""


def _recompile(manifest: ExpectedM1Manifest, observed_at: int) -> ExpectedM1Manifest:
    return compile_expected_m1_manifest(
        provider=manifest.provider, symbol=manifest.symbol,
        venue=manifest.venue, price_side=manifest.price_side,
        calendar_id=manifest.calendar_id,
        calendar_revision=manifest.calendar_revision,
        calendar_source=manifest.calendar_source,
        observed_at_utc=observed_at,
        sessions_utc=list(manifest.sessions_utc),
        exclusions_utc=list(manifest.exclusions_utc),
    )


async def review_twelvedata_completed_m1(
    *, api_key: str, manifest: ExpectedM1Manifest,
    owner_approved_api_credit_use: bool = False,
    owner_asserted_data_rights: bool = False,
    budget_db_path: str | None = None,
    budget_request_id: str | None = None,
) -> dict:
    """One operator-invoked HTTPS read, stamped by backend clock after response.

    This is a prospective *observation* only, not an independent provider,
    calendar, entitlement, executable-price or live-status attestation. The
    fixed XAU/USD mapping comes from the existing historical Twelve Data client.
    """
    if (not isinstance(api_key, str) or not 1 <= len(api_key) <= 512
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in api_key)):
        raise ProspectiveReceiptError("Invalid credential shape")
    # No potentially billable vendor request without two explicit per-call
    # owner declarations. These are NOT independently verified entitlements.
    # Exact booleans reject truthy strings and integers.
    if (owner_approved_api_credit_use is not True
            or owner_asserted_data_rights is not True):
        raise ProspectiveReceiptError("Explicit per-call API-credit and data-rights approval required")
    if type(manifest) is not ExpectedM1Manifest or (
        manifest.provider, manifest.symbol, manifest.venue, manifest.price_side
    ) != _IDENTITY:
        raise ProspectiveReceiptError("Unapproved provider, symbol, venue or price side")
    if not 1 <= len(manifest.expected_minutes) <= _MAX_EXPECTED:
        raise ProspectiveReceiptError("Expected-bar population exceeds provider request limit")

    request_at = int(_wall_clock())
    if not 60 <= request_at <= 253402300799:
        raise ProspectiveReceiptError("Invalid backend observation clock")
    try:
        # Verify immutable operator manifest before any chargeable vendor call.
        if _recompile(manifest, manifest.observed_at_utc) != manifest:
            raise ValueError("Manifest mutation")
        if manifest.observed_at_utc > request_at or manifest.expected_minutes[-1] + 60 > request_at:
            raise ValueError("Future expected bars")
    except (ValueError, TypeError, OverflowError):
        raise ProspectiveReceiptError("Invalid or uncompleted expected-bar manifest") from None

    # Reserve BEFORE any potentially chargeable network request. A failed or
    # uncertain request consumes its reservation; never retry or refund blindly.
    try:
        budget = reserve_one_credit(
            budget_db_path, request_id=budget_request_id,
            manifest_sha256=manifest.manifest_sha256,
        )
    except CreditBudgetError:
        raise ProspectiveReceiptError("Durable provider credit reservation required") from None

    started = _monotonic()
    try:
        rows, snapshot, wire = await retrieve(
            api_key, "XAUUSD-TD", len(manifest.expected_minutes),
            manifest.expected_minutes[-1], request_at,
            include_wire_evidence=True,
        )
        received_at = int(_wall_clock())
        elapsed = _monotonic() - started
        if (not math.isfinite(elapsed) or elapsed < 0 or elapsed > 60
                or received_at < request_at
                or abs((received_at - request_at) - elapsed) > 5):
            raise ValueError("Unreliable server clock")
        verify_normalized_snapshot(rows, snapshot, "XAU/USD")
        # Evidence is emitted by the bounded HTTP adapter, never caller-supplied.
        # It proves internal receipt-byte accounting, NOT vendor signing/rights.
        if (type(wire) is not dict or set(wire) != {
            "decoded_http_body_sha256", "decoded_http_body_bytes",
            "normalized_snapshot_sha256", "http_status",
            "provider_credit_header_observation",
        } or type(wire["decoded_http_body_bytes"]) is not int
                or not 0 < wire["decoded_http_body_bytes"] <= 3_000_000
                or type(wire["http_status"]) is not int or wire["http_status"] != 200
                or any(type(wire[k]) is not str or
                       re.fullmatch(r"[0-9a-f]{64}", wire[k]) is None
                       for k in ("decoded_http_body_sha256", "normalized_snapshot_sha256"))
                or wire["normalized_snapshot_sha256"] != hashlib.sha256(snapshot).hexdigest()):
            raise ValueError("Invalid provider wire evidence")
        credit_headers = wire["provider_credit_header_observation"]
        if (type(credit_headers) is not dict or set(credit_headers) != {
            "status", "api_credits_used", "api_credits_left",
            "quota_window_verified", "account_usage_reconciled",
        } or credit_headers["status"] not in (
            "OBSERVED_UNVERIFIED", "MISSING_REVIEW_REQUIRED",
        ) or credit_headers["quota_window_verified"] is not False
                or credit_headers["account_usage_reconciled"] is not False):
            raise ValueError("Invalid provider credit header observation")
        used = credit_headers["api_credits_used"]
        left = credit_headers["api_credits_left"]
        if credit_headers["status"] == "MISSING_REVIEW_REQUIRED":
            if used is not None or left is not None:
                raise ValueError("Invalid missing provider credit header pair")
        elif (type(used) is not int or type(left) is not int
                or not 1 <= used <= 1_000_000_000
                or not 0 <= left <= 1_000_000_000
                or used + left > 1_000_000_000):
            raise ValueError("Invalid provider credit counters")
        # No price-side inference: Twelve Data's normalized OHLC do not prove
        # an executable BID, ASK or spread, even over authenticated HTTPS.
        receipts = [{
            "provider": _IDENTITY[0], "symbol": _IDENTITY[1],
            "venue": _IDENTITY[2], "price_side": _IDENTITY[3],
            "bar_start_utc": row["time"], "received_at_utc": received_at,
            "open": row["open"], "high": row["high"],
            "low": row["low"], "close": row["close"],
        } for row in rows]
        server_manifest = _recompile(manifest, received_at)
        if server_manifest.expected_minutes != manifest.expected_minutes:
            raise ValueError("Expected-bar population changed")
        report = audit_m1_receipts_against_manifest(receipts, server_manifest)
        if credit_headers["status"] == "MISSING_REVIEW_REQUIRED":
            report["status"] = "REVIEW_REQUIRED"
    except (ProviderError, ValueError, TypeError, OverflowError, OSError, KeyError):
        raise ProspectiveReceiptError("Provider receipt rejected; no data accepted") from None

    report.update({
        "protocol": "one-shot-twelvedata-m1-observation-v1",
        "source_endpoint": "https://api.twelvedata.com/time_series",
        "instrument_mapping": "XAUUSD-TD -> XAU/USD",
        "operator_manifest_sha256": manifest.manifest_sha256,
        "server_manifest_sha256": server_manifest.manifest_sha256,
        "server_request_started_at_utc": request_at,
        "server_response_received_at_utc": received_at,
        "server_request_elapsed_ms": round(elapsed * 1000),
        "server_receipt_time_observed": True,
        "source_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "decoded_http_body_sha256": wire["decoded_http_body_sha256"],
        "decoded_http_body_bytes": wire["decoded_http_body_bytes"],
        "http_body_hash_semantics": "httpx-decoded-response-body-not-TLS-wire",
        "provider_http_status": wire["http_status"],
        "provider_credit_header_status": credit_headers["status"],
        "provider_api_credits_used": used,
        "provider_api_credits_left": left,
        "provider_credit_quota_window_verified": False,
        "provider_account_credit_usage_reconciled": False,
        "source_authenticated": False,
        "owner_call_approval_scope": "explicit-per-call-assertion-plus-durable-budget",
        "credit_budget_reservation_id": budget["reservation_id"],
        "credit_budget_utc_day": budget["utc_day"],
        "credit_budget_remaining_after_reservation": budget["remaining_credits"],
        "credit_budget_is_entitlement_proof": False,
        "provider_entitlement_verified": False,
        "retention_and_display_rights_verified": False,
        "expected_calendar_verified": False,
        "executable_bid_ask_verified": False,
        "live": False,
        "may_execute_order": False,
        "caveat": "One-shot provider response with backend-observed receipt time; vendor rights, price side, calendar and market freshness remain unverified. Not live or trade-authorizing.",
    })
    return report
