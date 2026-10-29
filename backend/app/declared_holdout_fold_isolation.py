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
    tightest_label_embargo_transition_index = None
    min_selection_gap = None
    tightest_selection_gap_index = None
    max_label_tail = 0
    longest_label_tail_fold_index = None
    total_pending_labels = 0
    max_pending_labels = 0
    most_pending_labels_fold_index = None
    max_last_decision_to_window_end_seconds = 0
    min_nonempty_decision_quarters = None
    max_single_quarter_share_basis_points = -1
    most_concentrated_quarter_fold_index = None
    sparsest_decision_quarters_fold_index = None
    longest_last_decision_gap_fold_index = None
    previous_census = None
    validation_cutoff_transitions = []
    total_prior_labels_unavailable_at_validation = 0
    max_prior_labels_unavailable_at_validation = 0
    most_unavailable_at_validation_later_fold_index = None
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
            # A later fold's validation cutoff can precede the availability
            # of previous-fold labels, even when selection-time embargo passes.
            # This is diagnostic only: the later validation may legitimately
            # exclude those labels, and membership does not prove data lineage.
            unavailable_at_validation = sum(
                row["label_available_at_utc"] > manifest["validation_end_at_utc"]
                for row in previous_census
            )
            validation_cutoff_transitions.append({
                "later_fold_index": index,
                "declared_prior_labels_unavailable_at_validation_end_count":
                    unavailable_at_validation,
            })
            total_prior_labels_unavailable_at_validation += unavailable_at_validation
            if unavailable_at_validation > max_prior_labels_unavailable_at_validation:
                max_prior_labels_unavailable_at_validation = unavailable_at_validation
                most_unavailable_at_validation_later_fold_index = index
            # Independent of label maturity, expose how close the next
            # candidate selection was to the previous declared holdout end.
            selection_gap = manifest["selected_at_utc"] - previous_end
            if min_selection_gap is None or selection_gap < min_selection_gap:
                min_selection_gap = selection_gap
                tightest_selection_gap_index = index
            label_embargo_slack = (manifest["selected_at_utc"] -
                                   previous_max_label - manifest["embargo_seconds"])
            if label_embargo_slack < 0:
                raise ValueError("Earlier fold labels not mature before later selection embargo")
            # Stable tie-break: the earliest equally tight transition wins.
            if (min_label_embargo_slack is None or
                    label_embargo_slack < min_label_embargo_slack):
                min_label_embargo_slack = label_embargo_slack
                tightest_label_embargo_transition_index = index
        rows = {row["row_sha256"] for row in census}
        if rows & seen_rows:
            raise ValueError("Cross-fold row identity reused")
        seen_rows.update(rows)
        seen_archives.add(archive)
        seen_manifest_hashes.add(digest)
        previous_end = manifest["holdout_end_at_utc"]
        previous_max_label = max(row["label_available_at_utc"] for row in census)
        previous_census = census
        # A label can mature after the decision window closes. Surface this
        # declared release-readiness risk without reading outcome values.
        label_tail = max(0, previous_max_label - previous_end)
        # A window can close with multiple unresolved trade labels, even if
        # their longest maturity tail is only one second. Count every row,
        # not merely the last decision or latest available label.
        pending_labels = sum(
            row["label_available_at_utc"] > previous_end for row in census
        )
        # A multi-year window can contain decisions in only a few early days.
        # These are coverage diagnostics, NOT proof of missing source candles:
        # a strategy may legitimately produce no later trade decisions.
        first_decision = census[0]["decision_at_utc"]
        last_decision = census[-1]["decision_at_utc"]
        decision_span = last_decision - first_decision
        last_decision_to_end = previous_end - last_decision
        max_interdecision_gap = (
            max(census[i]["decision_at_utc"] - census[i - 1]["decision_at_utc"]
                for i in range(1, len(census)))
            if len(census) > 1 else None
        )
        # Four equal-duration, half-open quarters of the declared window.
        # These count strategy decisions, not availability of source candles.
        window_start = manifest["holdout_start_at_utc"]
        window_duration = previous_end - window_start
        quarter_counts = [0, 0, 0, 0]
        for row in census:
            quarter = 4 * (row["decision_at_utc"] - window_start) // window_duration
            quarter_counts[quarter] += 1  # validated decision < window end
        nonempty_quarters = sum(count > 0 for count in quarter_counts)
        # Integer basis points avoid floating-point drift and distinguish
        # [97, 1, 1, 1] from [25, 25, 25, 25] even though both touch
        # all four quarters. This measures decisions, NOT candle coverage.
        largest_quarter_share_bp = 10000 * max(quarter_counts) // len(census)
        if largest_quarter_share_bp > max_single_quarter_share_basis_points:
            max_single_quarter_share_basis_points = largest_quarter_share_bp
            most_concentrated_quarter_fold_index = index
        if (min_nonempty_decision_quarters is None or
                nonempty_quarters < min_nonempty_decision_quarters):
            min_nonempty_decision_quarters = nonempty_quarters
            sparsest_decision_quarters_fold_index = index
        if last_decision_to_end > max_last_decision_to_window_end_seconds:
            max_last_decision_to_window_end_seconds = last_decision_to_end
            longest_last_decision_gap_fold_index = index
        total_pending_labels += pending_labels
        if pending_labels > max_pending_labels:
            max_pending_labels = pending_labels
            most_pending_labels_fold_index = index
        if label_tail > max_label_tail:
            max_label_tail = label_tail
            longest_label_tail_fold_index = index
        summaries.append({
            "manifest_sha256": digest,
            "archive_sha256": archive,
            "holdout_start_at_utc": manifest["holdout_start_at_utc"],
            "holdout_end_at_utc": previous_end,
            "observation_count": len(census),
            "first_declared_decision_at_utc": first_decision,
            "last_declared_decision_at_utc": last_decision,
            "declared_decision_span_seconds": decision_span,
            "declared_decision_quarter_counts": quarter_counts,
            "declared_largest_quarter_decision_share_basis_points": largest_quarter_share_bp,
            "declared_nonempty_decision_quarter_count": nonempty_quarters,
            "max_declared_interdecision_gap_seconds": max_interdecision_gap,
            "declared_last_decision_to_window_end_seconds": last_decision_to_end,
            "latest_declared_label_available_at_utc": previous_max_label,
            "declared_label_tail_beyond_window_seconds": label_tail,
            "declared_labels_pending_at_window_end_count": pending_labels,
        })
    return {
        "protocol": "declared-holdout-fold-isolation-v1",
        "status": "DECLARED_MEMBERSHIP_ONLY",
        "fold_count": len(folds),
        "max_declared_label_tail_beyond_window_seconds": max_label_tail,
        "longest_declared_label_tail_fold_index": longest_label_tail_fold_index,
        "total_declared_labels_pending_at_window_end_count": total_pending_labels,
        "max_declared_labels_pending_at_window_end_count": max_pending_labels,
        "most_pending_declared_labels_fold_index": most_pending_labels_fold_index,
        "observation_count": len(seen_rows),
        "min_declared_nonempty_decision_quarter_count": min_nonempty_decision_quarters,
        "max_declared_largest_quarter_decision_share_basis_points": max_single_quarter_share_basis_points,
        "most_concentrated_quarter_fold_index": most_concentrated_quarter_fold_index,
        "sparsest_declared_decision_quarters_fold_index": sparsest_decision_quarters_fold_index,
        "max_declared_last_decision_to_window_end_seconds":
            max_last_decision_to_window_end_seconds,
        "longest_declared_last_decision_gap_fold_index":
            longest_last_decision_gap_fold_index,
        "declared_validation_cutoff_transitions": validation_cutoff_transitions,
        "total_declared_prior_labels_unavailable_at_validation_end_count":
            total_prior_labels_unavailable_at_validation,
        "max_declared_prior_labels_unavailable_at_validation_end_count":
            max_prior_labels_unavailable_at_validation,
        "most_unavailable_at_validation_later_fold_index":
            most_unavailable_at_validation_later_fold_index,
        "min_declared_label_embargo_slack_seconds": min_label_embargo_slack,
        "tightest_declared_label_embargo_later_fold_index": tightest_label_embargo_transition_index,
        "min_declared_interfold_selection_gap_seconds": min_selection_gap,
        "tightest_declared_selection_gap_later_fold_index": tightest_selection_gap_index,
        "folds": summaries,
        "source_bytes_independently_authenticated": False,
        "holdout_untouched_independently_verified": False,
        "broker_costs_verified": False,
        "profitable_edge_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "Only caller-declared manifests and membership were checked. "
                   "Embargo slack and validation-cutoff availability use unverified declared clocks; "
                   "a positive validation count does not prove outcome reuse or leakage. "
                   "Distinct archive digests do not prove independent market data. "
                   "Decision-time gaps, empty quarters and concentration do not establish missing source coverage. "
                   "No holdout outcomes, executable costs or trading permissions are evaluated."
    }
