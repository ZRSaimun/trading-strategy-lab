"""Offline comparison of two untrusted HistData archive audit inventories.

No source ZIP access, vendor calls, price repairs, database writes, or trading.
"""
from __future__ import annotations

import argparse
import json

from .histdata_audit_triage import (
    _read_regular_bounded, _reject_constant, _strict_pairs, triage_histdata_audit,
)

# These are *reported* properties, not independently verified source facts.
_CLAIM_FIELDS = (
    "archive_bytes", "instrument", "format", "price_side",
    "fixed_utc_offset_minutes", "rows", "unique_timestamps",
    "duplicate_timestamps", "conflicting_duplicate_ohlc",
    "backward_timestamp_jumps", "invalid_rows", "outside_filename_period_rows",
    "zero_volume_rows", "first_local_EST", "last_local_EST",
    "first_utc", "last_utc", "observed_gap_events",
    "unobserved_minutes_between_rows", "largest_gap_minutes",
    "canonical_bid_ohlc_sha256", "status",
)


def compare_archive_inventories(previous: dict, current: dict, *, sample_limit: int = 20) -> dict:
    """Report identity/claim changes without interpreting them as market revisions."""
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid sample limit")
    # Reject malformed summaries, inconsistent counters, ambiguous identities and
    # unsupported rights/execution claims before comparing any metadata.
    triage_histdata_audit(previous)
    triage_histdata_audit(current)
    before = {item["file"]: item for item in previous["archives"]}
    after = {item["file"]: item for item in current["archives"]}
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    byte_changes = []
    claim_changes = []
    unchanged = 0
    for name in sorted(before.keys() & after.keys()):
        old, new = before[name], after[name]
        bytes_changed = old["archive_sha256"] != new["archive_sha256"]
        fields_changed = [field for field in _CLAIM_FIELDS if old.get(field) != new.get(field)]
        if bytes_changed:
            byte_changes.append(name)
        if fields_changed:
            claim_changes.append((name, fields_changed, not bytes_changed))
        if not bytes_changed and not fields_changed:
            unchanged += 1

    # A renamed file with the same reported byte digest is a *candidate* alias;
    # it is not an independent source or permission to deduplicate/merge.
    removed_hashes = {before[name]["archive_sha256"]: name for name in removed}
    aliases = [(removed_hashes[after[name]["archive_sha256"]], name)
               for name in added if after[name]["archive_sha256"] in removed_hashes]
    if byte_changes or claim_changes:
        outcome = "REVIEW_IDENTITY_OR_METADATA_CHANGE"
    elif added or removed:
        outcome = "INVENTORY_MEMBERSHIP_CHANGED"
    else:
        outcome = "NO_REPORTED_DIFFERENCES"
    return {
        "result": "UNTRUSTED_ARCHIVE_INVENTORY_COMPARISON",
        "outcome": outcome,
        "summary": {
            "previous_archives": len(before), "current_archives": len(after),
            "shared_filenames": len(before.keys() & after.keys()),
            "unchanged_shared_filenames": unchanged,
            "added_filenames": len(added), "removed_filenames": len(removed),
            "same_filename_changed_zip_digest": len(byte_changes),
            "same_filename_changed_claims": len(claim_changes),
            "same_zip_digest_changed_claims": sum(same_bytes for _, _, same_bytes in claim_changes),
            "removed_added_same_digest_alias_candidates": len(aliases),
        },
        "added_filename_samples": added[:sample_limit],
        "removed_filename_samples": removed[:sample_limit],
        "changed_zip_filename_samples": byte_changes[:sample_limit],
        "changed_claim_samples": [
            {"archive": name, "changed_fields": fields,
             "same_reported_zip_digest": same_bytes}
            for name, fields, same_bytes in claim_changes[:sample_limit]
        ],
        "possible_rename_samples": [
            {"previous_file": old, "current_file": new,
             "independent_source_verified": False}
            for old, new in aliases[:sample_limit]
        ],
        "sample_limit": sample_limit,
        "raw_zip_bytes_verified": False,
        "source_authenticity_verified": False,
        "source_usage_rights_verified": False,
        "market_calendar_verified": False,
        "research_ready": False,
        "can_auto_import": False,
        "live": False,
        "may_execute_order": False,
        "limitations": "Compares untrusted scanner claims only. Digest or metadata changes are not proof of vendor revisions, price changes, tampering, rights or tradable minutes.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline HistData audit-inventory drift comparison")
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        def read(path):
            return json.loads(_read_regular_bounded(path, 5_000_000),
                              object_pairs_hook=_strict_pairs,
                              parse_constant=_reject_constant)
        result = compare_archive_inventories(read(args.previous), read(args.current),
                                             sample_limit=args.sample_limit)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError):
        print(json.dumps({"result": "REJECTED", "research_ready": False,
                          "can_auto_import": False, "live": False,
                          "may_execute_order": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
