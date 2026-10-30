"""Owner-invoked, budgeted DEMO metadata preflight; never a market-price feed.

No automatic calls, routes, startup hooks, storage, retries, or order methods.
Returns a redacted observation only. Caller must secure keys and private ledger.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import re

from app.trading212_demo_metadata_schema import (
    DemoMetadataSchemaError, validate_demo_metadata_shape,
)

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST = re.compile(r"[0-9a-f]{32}\Z")
_ENDPOINTS = frozenset({"instruments", "exchanges"})
_QUOTA_STATUSES = frozenset({
    "MISSING_REVIEW_REQUIRED", "PARTIAL_REVIEW_REQUIRED",
    "INCONSISTENT_REVIEW_REQUIRED", "OBSERVED_UNVERIFIED",
})


class DemoStagingProbeError(ValueError):
    """No credentials, broker payloads or private account identifiers in errors."""


def _validate_receipt(receipt: object, *, endpoint: str, account_type: str) -> dict:
    if not isinstance(receipt, dict):
        raise DemoStagingProbeError("Invalid metadata receipt")
    if (receipt.get("provider") != "Trading 212"
            or receipt.get("endpoint") != endpoint
            or receipt.get("environment") != "DEMO"
            or receipt.get("account_type_declared") != account_type
            or any(receipt.get(flag) is not False for flag in (
                "account_type_verified", "server_clock_attested",
                "market_data_feed", "price_freshness_verified",
                "cfd_supported", "may_execute_order",
            ))):
        raise DemoStagingProbeError("Metadata receipt has invalid provenance")
    digest = receipt.get("response_sha256")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise DemoStagingProbeError("Invalid metadata response fingerprint")
    observed = receipt.get("received_at_utc")
    if not isinstance(observed, str) or len(observed) > 40:
        raise DemoStagingProbeError("Invalid local receipt timestamp")
    try:
        at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        raise DemoStagingProbeError("Invalid local receipt timestamp") from None
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise DemoStagingProbeError("UTC local receipt timestamp required")
    payload = receipt.get("data")
    try:
        count = validate_demo_metadata_shape(endpoint, payload)
    except DemoMetadataSchemaError:
        raise DemoStagingProbeError("Invalid DEMO metadata schema") from None
    quota = receipt.get("rate_limit_observation")
    if (not isinstance(quota, dict)
            or not isinstance(quota.get("status"), str)
            or quota["status"] not in _QUOTA_STATUSES
            or quota.get("account_quota_verified") is not False
            or quota.get("safe_to_make_another_request") is not False):
        raise DemoStagingProbeError("Invalid broker quota observation")
    # This is only a local receipt and a caller-declared account scope. Even a
    # successful authenticated GET cannot attest licensing or live CFD prices.
    return {
        "status": ("DEMO_METADATA_OBSERVED_UNVERIFIED"
                   if payload and quota["status"] == "OBSERVED_UNVERIFIED"
                   else "REVIEW_REQUIRED"),
        "provider": "Trading 212", "environment": "DEMO",
        "endpoint": endpoint, "account_type_declared": account_type,
        "received_at_utc_local_unverified": observed,
        "response_sha256": digest, "declared_items_count": count,
        "rate_limit_status": quota["status"],
        "account_type_verified": False, "provider_entitlement_verified": False,
        "data_rights_verified": False, "server_clock_attested": False,
        "market_data_feed": False, "price_freshness_verified": False,
        "cfd_supported": False, "may_execute_order": False,
    }


def probe_trading212_demo_metadata(
    *, owner_confirmed: bool = False, db_path: str,
    request_id: str, account_scope_sha256: str, endpoint: str,
    account_type: str, api_key: str, api_secret: str, transport=None,
) -> dict:
    """One explicit budgeted DEMO metadata GET, returning only redacted evidence.

    This function is never scheduled or invoked by the website. The caller
    must independently verify key permissions, rights and ledger durability.
    Failed HTTP calls still consume a reservation; there are no retries.
    """
    if (owner_confirmed is not True or not isinstance(endpoint, str)
            or endpoint not in _ENDPOINTS
            or account_type not in ("INVEST", "STOCKS_ISA")
            or not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id)):
        raise DemoStagingProbeError("Explicit eligible DEMO metadata approval required")
    from app.trading212_request_budget import fetch_budgeted_trading212_readonly
    receipt = fetch_budgeted_trading212_readonly(
        db_path=db_path, request_id=request_id,
        account_scope_sha256=account_scope_sha256,
        endpoint=endpoint, account_type=account_type, environment="DEMO",
        api_key=api_key, api_secret=api_secret, transport=transport,
    )
    result = _validate_receipt(receipt, endpoint=endpoint, account_type=account_type)
    # Correlate to the caller's already-reserved request without publishing its
    # raw ID, account scope, credential pair, or private metadata payload.
    result["request_id_sha256"] = hashlib.sha256(request_id.encode("ascii")).hexdigest()
    return result
