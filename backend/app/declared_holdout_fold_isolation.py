"""Offline cross-fold holdout *membership* audit; no outcomes or broker access.

All evidence is caller-declared. This does not certify source authenticity,
independent preregistration, untouched holdouts or profitable performance.
"""
from __future__ import annotations

from .declared_holdout_release_gate import _validate_manifest, _validate_census, _hash

_MAX_FOLDS = 24
_KEYS = {"manifest", "census"}


def audit_declared_holdout_fold_isolation(folds):
    """Fail closed on reused archive/row identity and overlapping fold windows.

    This is for a single fixed candidate evaluated across strictly disjoint,
    independently identified, caller-declared holdout windows. No outcome data
    are accepted, inspected or returned.
    """
    if type(folds) is not list or not 2 <= len(folds) <= _MAX_FOLDS:
        raise ValueError("Expected 2..24 declared holdout folds")

    seen_archives, seen_rows, seen_manifest_hashes = set(), set(), set()
    previous_end = None
    previous_max_label = None
    min_label_embargo_slack = None
    study_id = candidate_id = candidate_sha = source_signature = None
    summaries = []
    for index, fold in enumerate(folds):
        if type(fold) is not dict or set(fold) != _KEYS:
            raise ValueError("Invalid exact fold schema (outcomes forbidden)")
        manifest, census = fold["manifest"], fold["census"]
        _validate_manifest(manifest)
        _validate_census(manifest, census)
        source = manifest["source"]
        signature = tuple(source[k] for k in (
            "provider", "venue", "instrument", "quote_side", "account_alias",
            "settlement_currency", "utc_convention"))
        if index == 0:
            study_id, candidate_id = manifest["study_id"], manifest["candidate_id"]
            candidate_sha, source_signature = manifest["candidate_config_sha256"], signature
        elif (manifest["study_id"] != study_id or
              manifest["candidate_id"] != candidate_id or
              manifest["candidate_config_sha256"] != candidate_sha or
              signature != source_signature):
            raise ValueError("Cross-fold study/candidate/source convention changed")
        archive = source["archive_sha256"]
        digest = _hash(manifest)
        if archive in seen_archives or digest in seen_manifest_hashes:
            raise ValueError("Reused archive or manifest across declared holdout folds")
        if previous_end is not None:
            if manifest["holdout_start_at_utc"] < previous_end:
                raise ValueError("Overlapping or out-of-order holdout windows")
            if manifest["selected_at_utc"] < previous_end:
                raise ValueError("Later fold candidate selection overlaps previous holdout")
            label_embargo_slack = (manifest["selected_at_utc"] -
                                   previous_max_label - manifest["embargo_seconds"])
            if label_embargo_slack < 0:
                raise ValueError("Earlier fold labels not mature before later selection embargo")
            min_label_embargo_slack = (label_embargo_slack if min_label_embargo_slack is None
                                      else min(min_label_embargo_slack, label_embargo_slack))
        rows = {row["row_sha256"] for row in census}
        if rows & seen_rows:
            raise ValueError("Cross-fold row identity reused")
        seen_rows.update(rows)
        seen_archives.add(archive)
        seen_manifest_hashes.add(digest)
        previous_end = manifest["holdout_end_at_utc"]
        previous_max_label = max(row["label_available_at_utc"] for row in census)
        summaries.append({
            "manifest_sha256": digest,
            "archive_sha256": archive,
            "holdout_start_at_utc": manifest["holdout_start_at_utc"],
            "holdout_end_at_utc": previous_end,
            "observation_count": len(census),
        })
    return {
        "protocol": "declared-holdout-fold-isolation-v1",
        "status": "DECLARED_MEMBERSHIP_ONLY",
        "fold_count": len(folds),
        "observation_count": len(seen_rows),
        "min_declared_label_embargo_slack_seconds": min_label_embargo_slack,
        "folds": summaries,
        "source_bytes_independently_authenticated": False,
        "holdout_untouched_independently_verified": False,
        "broker_costs_verified": False,
        "profitable_edge_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "Only caller-declared manifests and membership were checked. "
                   "Embargo slack is computed from unverified declared clocks, not proof of leakage prevention. "
                   "Distinct archive digests do not prove independent market data. "
                   "No holdout outcomes, executable costs or trading permissions are evaluated."
    }
