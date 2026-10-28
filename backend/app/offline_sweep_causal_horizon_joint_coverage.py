"""Retrospective structural cross-tab of causal vs full-horizon M15 eligibility.

Never use full-horizon classifications to select, filter or rank signals:
they inspect bars that were not known at the completed confirmation.
"""
from __future__ import annotations

from datetime import timedelta

from .offline_sweep_duplicate_bucket_sensitivity import (
    _parse_clock, _quarter_hour, audit_declared_duplicate_minutes,
)

_STEP = timedelta(minutes=15)
_COHORTS = ("development", "exploratory_later")
_CAUSAL = ("gap_or_segment", "declared_duplicate_touched", "quarantine_clean")
_HORIZON = ("outside_cohort_or_archive", "gap_or_segment",
            "declared_duplicate_touched", "quarantine_clean")


def audit_causal_horizon_joint_coverage(
        bars, duplicate_m1_times, *, dataset_id, archive_sha256):
    """Count joint structural populations without changing any research rules.

    Causal classification uses only 16 prior, sweep and completed
    confirmation M15 bars. The horizon classification is *ex post only*,
    requiring another 16 M15 bars. Neither classification uses prices,
    future outcomes or strategy signals. The original frozen research
    is executed by the parent auditor to validate identical input.
    """
    parent = audit_declared_duplicate_minutes(
        bars, duplicate_m1_times, dataset_id=dataset_id,
        archive_sha256=archive_sha256,
    )
    n = len(bars)
    split = n * 7 // 10
    present = {bar.time for bar in bars}
    touched = {
        _quarter_hour(_parse_clock(stamp))
        for stamp in duplicate_m1_times
    } & present

    broken = [0] * (n + 1)
    contaminated = [0] * (n + 1)
    for j, bar in enumerate(bars):
        is_broken = j > 0 and (
            bar.segment != bars[j - 1].segment or
            bar.time - bars[j - 1].time != _STEP
        )
        broken[j + 1] = broken[j] + int(is_broken)
        contaminated[j + 1] = contaminated[j] + int(bar.time in touched)

    matrix = {
        cohort: {
            causal: {horizon: 0 for horizon in _HORIZON}
            for causal in _CAUSAL
        } for cohort in _COHORTS
    }
    for i in range(16, n - 1):
        cohort = ("development" if i + 1 < split - 16 else
                  "exploratory_later" if i >= split + 16 else None)
        if cohort is None:
            continue
        start, causal_end = i - 16, i + 1
        if broken[causal_end + 1] - broken[start + 1]:
            causal = "gap_or_segment"
        elif contaminated[causal_end + 1] - contaminated[start]:
            causal = "declared_duplicate_touched"
        else:
            causal = "quarantine_clean"

        # RETROSPECTIVE ONLY. Never feed this class into signal admission.
        horizon_end = i + 17
        if (horizon_end >= n or
                (cohort == "development" and horizon_end >= split - 16)):
            horizon = "outside_cohort_or_archive"
        elif broken[horizon_end + 1] - broken[start + 1]:
            horizon = "gap_or_segment"
        elif contaminated[horizon_end + 1] - contaminated[start]:
            horizon = "declared_duplicate_touched"
        else:
            horizon = "quarantine_clean"
        matrix[cohort][causal][horizon] += 1

    result = {}
    causal_keys = {
        "gap_or_segment": "confirmation_crosses_source_gap_or_segment",
        "declared_duplicate_touched":
            "declared_duplicate_touched_confirmation_windows",
        "quarantine_clean": "quarantine_clean_confirmation_windows",
    }
    horizon_keys = {
        "outside_cohort_or_archive": "full_horizon_outside_cohort_or_archive",
        "gap_or_segment": "full_horizon_crosses_source_gap_or_segment",
        "declared_duplicate_touched":
            "declared_duplicate_touched_full_horizon_windows",
        "quarantine_clean": "quarantine_clean_full_horizon_windows",
    }
    for cohort in _COHORTS:
        cells = matrix[cohort]
        causal_ref = parent["causal_confirmation_window_coverage"][
            "cohorts"][cohort]
        horizon_ref = parent["full_horizon_window_coverage"]["cohorts"][cohort]
        total = sum(sum(row.values()) for row in cells.values())
        if (total != causal_ref["possible_sweep_indices"] or
                total != horizon_ref["possible_sweep_indices"]):
            raise RuntimeError("Joint structural denominator mismatch")
        for causal, ref_key in causal_keys.items():
            if sum(cells[causal].values()) != causal_ref[ref_key]:
                raise RuntimeError("Causal structural marginal mismatch")
        for horizon, ref_key in horizon_keys.items():
            if sum(cells[causal][horizon] for causal in _CAUSAL) != (
                    horizon_ref[ref_key]):
                raise RuntimeError("Full-horizon structural marginal mismatch")
        if (cells["gap_or_segment"]["quarantine_clean"] or
                cells["declared_duplicate_touched"]["quarantine_clean"]):
            raise RuntimeError("Full-horizon clean contradicts causal history")
        clean = cells["quarantine_clean"]
        result[cohort] = {
            "possible_sweep_indices": total,
            "causal_by_retrospective_horizon": cells,
            "causal_clean_with_full_clean_horizon": clean["quarantine_clean"],
            "causal_clean_without_full_clean_horizon": sum(clean.values()) -
                clean["quarantine_clean"],
        }

    return {
        "audit": "SOURCE_LOCAL_CAUSAL_HORIZON_JOINT_STRUCTURE_V1",
        "dataset_id": dataset_id,
        "source_declared_archive_sha256": archive_sha256,
        "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC",
        "frozen_split": "70_30_BY_ORIGINAL_BAR_INDEX_WITH_16_BAR_EMBARGO",
        "causal_window": "PRIOR16_SWEEP1_COMPLETED_CONFIRMATION1",
        "retrospective_horizon_window": "CAUSAL18_PLUS_FUTURE16",
        "horizon_classification_is_post_outcome_only": True,
        "may_use_horizon_to_select_signals": False,
        "counts_are_trade_or_signal_performance": False,
        "original_source_authenticated": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "cohorts": result,
    }
