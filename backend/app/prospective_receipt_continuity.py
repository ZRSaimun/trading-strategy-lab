"""Offline, fail-closed continuity audit for two declared M1 receipt checkpoints.

This checks append-only *retained* receipt evidence, not two fresh vendor
polls. It never verifies a provider, entitlement, calendar or receipt clock.
No network, persistence, routes, orders, or implicit provider requests.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from .expected_bar_manifest import (
    ExpectedM1Manifest, audit_m1_receipts_against_manifest,
)

_PRICE_FIELDS = ("open", "high", "low", "close")
_ID_FIELDS = ("provider", "symbol", "venue", "price_side")


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def audit_declared_m1_receipt_continuity(
    previous_receipts: list[dict], current_receipts: list[dict],
    previous_manifest: ExpectedM1Manifest, current_manifest: ExpectedM1Manifest,
    *, sample_limit: int = 10,
) -> dict:
    """Compare two chronological, retained, caller-declared M1 checkpoints.

    Existing rows must be retained byte-for-byte at the field level: neither
    OHLC nor the originally declared receipt timestamp may be rewritten.
    Newly appearing older bars are reported as backfills, never as on-time
    prospective receipts. The expected population may only grow by suffix.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid continuity sample limit")
    if (type(previous_manifest) is not ExpectedM1Manifest
            or type(current_manifest) is not ExpectedM1Manifest):
        raise ValueError("Two compiled manifests required")
    if (tuple(getattr(previous_manifest, k) for k in _ID_FIELDS)
            != tuple(getattr(current_manifest, k) for k in _ID_FIELDS)):
        raise ValueError("Cannot compare different provider, instrument, venue or price side")
    if any(getattr(previous_manifest, k) != getattr(current_manifest, k)
           for k in ("calendar_id", "calendar_revision", "calendar_source")):
        raise ValueError("Calendar provenance changed; separate review required")
    if current_manifest.observed_at_utc <= previous_manifest.observed_at_utc:
        raise ValueError("Checkpoints must advance in observation time")
    earlier = previous_manifest.expected_minutes
    later = current_manifest.expected_minutes
    if later[:len(earlier)] != earlier:
        raise ValueError("Expected minute population was rewritten or contracted")

    # Both calls independently reconstruct their manifests and validate all
    # row identity, UTC chronology, OHLC, bounds, and declared freshness.
    previous = audit_m1_receipts_against_manifest(
        previous_receipts, previous_manifest, sample_limit=sample_limit)
    current = audit_m1_receipts_against_manifest(
        current_receipts, current_manifest, sample_limit=sample_limit)

    # A duplicate is already REVIEW_REQUIRED in the underlying census. Keep
    # the first record only for conservative continuity accounting.
    before = {row["bar_start_utc"]: row for row in reversed(previous_receipts)}
    after = {row["bar_start_utc"]: row for row in reversed(current_receipts)}
    removed = sorted(set(before) - set(after))
    common = set(before) & set(after)
    price_revisions = sorted(t for t in common if
                             any(before[t][k] != after[t][k] for k in _PRICE_FIELDS))
    timestamp_revisions = sorted(t for t in common if
                                 before[t]["received_at_utc"] != after[t]["received_at_utc"])
    new = set(after) - set(before)
    prior_expected = set(earlier)
    backfills = sorted(new & prior_expected)
    new_expected = sorted((new - prior_expected) & set(later))
    backdated = sorted(t for t in new
                       if after[t]["received_at_utc"] <= previous_manifest.observed_at_utc)
    anomalies = bool(removed or price_revisions or timestamp_revisions or backfills
                     or backdated or previous["status"] == "REVIEW_REQUIRED"
                     or current["status"] == "REVIEW_REQUIRED")
    digest = hashlib.sha256(json.dumps({
        "previous_manifest": previous_manifest.manifest_sha256,
        "current_manifest": current_manifest.manifest_sha256,
        "previous_receipts": previous["input_sha256"],
        "current_receipts": current["input_sha256"],
        "sample_limit": sample_limit,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "protocol": "declared-m1-receipt-continuity-v1",
        "status": "REVIEW_REQUIRED" if anomalies else "INTERNAL_CONTINUITY_ONLY_NOT_LIVE",
        "input_sha256": digest,
        "previous_census_status": previous["status"],
        "current_census_status": current["status"],
        "previous_expected_minutes": len(earlier),
        "current_expected_minutes": len(later),
        "previous_unique_observed_minutes": len(before),
        "current_unique_observed_minutes": len(after),
        "retained_unchanged_minutes": len(common - set(price_revisions) - set(timestamp_revisions)),
        "newly_observed_current_expected_minutes": len(new_expected),
        "backfilled_prior_expected_minutes": len(backfills),
        "removed_previous_minutes": len(removed),
        "revised_previous_ohlc_minutes": len(price_revisions),
        "rewritten_previous_receipt_times": len(timestamp_revisions),
        "backdated_new_receipt_times": len(backdated),
        "removed_utc_samples": [_iso(t) for t in removed[:sample_limit]],
        "revised_utc_samples": [_iso(t) for t in price_revisions[:sample_limit]],
        "retimestamped_utc_samples": [_iso(t) for t in timestamp_revisions[:sample_limit]],
        "backfilled_utc_samples": [_iso(t) for t in backfills[:sample_limit]],
        "backdated_utc_samples": [_iso(t) for t in backdated[:sample_limit]],
        "sample_limit": sample_limit,
        "source_authenticated": False,
        "expected_calendar_verified": False,
        "provider_entitlement_verified": False,
        "retention_and_display_rights_verified": False,
        "server_receipt_clock_attested": False,
        "executable_bid_ask_verified": False,
        "live": False,
        "may_execute_order": False,
        "caveat": "Offline declared retained checkpoints only. No verified provider, source clock, calendar, licensing, executable spread or live feed.",
    }
