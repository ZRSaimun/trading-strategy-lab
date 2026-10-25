"""Read-only drift report for two independently reconciled historical imports.

Not vendor attestation, licensing approval, a market-session completeness check,
trade eligibility, or permission to overwrite an existing dataset.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from .provider_staging_reconciliation import (
    _read_regular_bounded, _reject_constant, _strict_pairs,
    reconcile_staging_dataset,
)


def _utc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def compare_staging_snapshots(
    previous_manifest: dict, previous_archive: bytes, previous_candles: list[dict],
    current_manifest: dict, current_archive: bytes, current_candles: list[dict],
    *, sample_limit: int = 5,
) -> dict:
    """Describe observed OHLC revisions and coverage changes, never apply them.

    Both snapshots must first pass the complete independent offline reconciliation.
    A gap or missing timestamp is not proof of a provider outage or market opening.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 20:
        raise ValueError("sample_limit must be an integer from 0 to 20")
    old = reconcile_staging_dataset(previous_manifest, previous_archive, previous_candles)
    new = reconcile_staging_dataset(current_manifest, current_archive, current_candles)
    # Server-receipt timestamps are not provider-signed. This only prevents
    # accidental reverse comparisons, not tampering or clock manipulation.
    if current_manifest["response_received_at"] < previous_manifest["response_received_at"]:
        raise ValueError("Current snapshot predates previous server observation")

    def values(rows: list[dict]) -> dict[int, tuple]:
        return {r["time"]: (r["open"], r["high"], r["low"], r["close"], r.get("volume")) for r in rows}

    before = values(previous_candles)
    after = values(current_candles)
    common = before.keys() & after.keys()
    revised = sorted(t for t in common if before[t] != after[t])
    removed = sorted(before.keys() - after.keys())
    added = sorted(after.keys() - before.keys())
    unchanged = len(common) - len(revised)
    # Compare coverage only within the intersection of observed endpoint ranges.
    # Differences outside this overlap can be caused simply by shifting the
    # requested historical window. Endpoints are observations, NOT a verified
    # market calendar or a claim that every intervening minute should trade.
    overlap_start = max(min(before), min(after))
    overlap_end = min(max(before), max(after))
    has_overlap = overlap_start <= overlap_end
    added_inside = [t for t in added if has_overlap and overlap_start <= t <= overlap_end]
    removed_inside = [t for t in removed if has_overlap and overlap_start <= t <= overlap_end]
    added_outside = len(added) - len(added_inside)
    removed_outside = len(removed) - len(removed_inside)
    if not common:
        outcome = "NO_SHARED_OBSERVED_MINUTES"
    elif revised or removed or added:
        outcome = "OBSERVED_VALUE_OR_COVERAGE_DRIFT"
    else:
        outcome = "SAME_OBSERVED_VALUES_AND_COVERAGE"
    # A shifted request window is not by itself a revision of shared bars.
    # Keep the legacy outcome for existing consumers, but give reviewers a
    # narrower triage result that does not confuse edge changes with drift
    # inside the shared observed range. No classification authorizes imports.
    shared_interval_review_required = bool(revised or added_inside or removed_inside)
    if not common:
        comparison_class = "NO_SHARED_OBSERVED_MINUTES"
    elif shared_interval_review_required:
        comparison_class = "REVIEW_SHARED_INTERVAL_DRIFT"
    elif added or removed:
        comparison_class = "WINDOW_BOUNDARY_DIFFERENCE_ONLY"
    else:
        comparison_class = "IDENTICAL_OBSERVED_WINDOW"
    return {
        "result": "OFFLINE_HISTORICAL_DRIFT_OBSERVATION_ONLY",
        "outcome": outcome,
        "comparison_class": comparison_class,
        "shared_interval_review_required": shared_interval_review_required,
        "window_boundary_only_difference": comparison_class == "WINDOW_BOUNDARY_DIFFERENCE_ONLY",
        "provider": "twelvedata",
        "provider_symbol": "XAU/USD",
        "previous_archive_sha256": old["archive_sha256"],
        "current_archive_sha256": new["archive_sha256"],
        "previous_observed_candles": len(before),
        "current_observed_candles": len(after),
        "shared_observed_minutes": len(common),
        "unchanged_shared_minutes": unchanged,
        "revised_shared_minutes": len(revised),
        "removed_observed_minutes": len(removed),
        "added_observed_minutes": len(added),
        "observed_range_overlap": has_overlap,
        "observed_overlap_start_utc": _utc(overlap_start) if has_overlap else None,
        "observed_overlap_end_utc": _utc(overlap_end) if has_overlap else None,
        "added_within_observed_overlap": len(added_inside),
        "removed_within_observed_overlap": len(removed_inside),
        "added_outside_observed_overlap": added_outside,
        "removed_outside_observed_overlap": removed_outside,
        "overlap_coverage_differs": bool(added_inside or removed_inside),
        "revised_utc_samples": [_utc(t) for t in revised[:sample_limit]],
        "removed_utc_samples": [_utc(t) for t in removed[:sample_limit]],
        "added_utc_samples": [_utc(t) for t in added[:sample_limit]],
        "sample_limit": sample_limit,
        "source_authenticity_verified": False,
        "provider_entitlement_verified": False,
        "market_calendar_checked": False,
        "executable_bid_ask_verified": False,
        "live": False,
        "may_replace_dataset": False,
        "may_execute_order": False,
        "caveat": "Changes may reflect revisions, different request windows, closures or other causes; no cause or permission to overwrite is established.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only offline historical snapshot drift report")
    for version in ("previous", "current"):
        for name in ("manifest", "archive", "candles"):
            parser.add_argument(f"--{version}-{name}", required=True)
    parser.add_argument("--sample-limit", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        inputs = []
        for version in ("previous", "current"):
            manifest = json.loads(_read_regular_bounded(getattr(args, f"{version}_manifest"), 200_000),
                                  object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
            archive = _read_regular_bounded(getattr(args, f"{version}_archive"), 3_000_000)
            candles = json.loads(_read_regular_bounded(getattr(args, f"{version}_candles"), 2_000_000),
                                 object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
            inputs.extend((manifest, archive, candles))
        report = compare_staging_snapshots(*inputs, sample_limit=args.sample_limit)
    except (ValueError, OSError, TypeError, OverflowError, KeyError):
        print(json.dumps({"result": "REJECTED", "live": False, "may_replace_dataset": False,
                          "may_execute_order": False}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
