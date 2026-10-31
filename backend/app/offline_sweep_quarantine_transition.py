"""Read-only paired causal-window transitions between two declared M1 quarantines.

Structural candidate denominator comparison, NOT a matched-trade backtest,
source authentication, future-data filter, or broker order control.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from .offline_sweep_causal_cohort_identity import audit_causal_cohort_identity
from .offline_sweep_duplicate_bucket_sensitivity import _parse_clock, _quarter_hour

_STEP = timedelta(minutes=15)
_COHORTS = ("development", "exploratory_later")
_CLASSES = ("gap_or_segment", "declared_duplicate_touched", "quarantine_clean")


def audit_quarantine_transition(bars, baseline_duplicate_m1_times,
                                revised_duplicate_m1_times, *,
                                dataset_id, archive_sha256):
    """Cross-tab the same source-local 18-bar candidates under two declarations.

    Both declarations are independently validated by the frozen audit. The
    original bars, split, source identity and indices remain unchanged.
    """
    baseline = audit_causal_cohort_identity(
        bars, baseline_duplicate_m1_times,
        dataset_id=dataset_id, archive_sha256=archive_sha256)
    revised = audit_causal_cohort_identity(
        bars, revised_duplicate_m1_times,
        dataset_id=dataset_id, archive_sha256=archive_sha256)
    present = {bar.time for bar in bars}
    touched = []
    for declared in (baseline_duplicate_m1_times, revised_duplicate_m1_times):
        touched.append({_quarter_hour(_parse_clock(t)) for t in declared} & present)
    n = len(bars)
    split = n * 7 // 10
    broken = [0] * (n + 1)
    marks = [[0] * (n + 1), [0] * (n + 1)]
    for j, bar in enumerate(bars):
        broken[j + 1] = broken[j] + int(j > 0 and (
            bar.segment != bars[j - 1].segment or
            bar.time - bars[j - 1].time != _STEP))
        for side in range(2):
            marks[side][j + 1] = marks[side][j] + int(bar.time in touched[side])

    result = {}
    for cohort in _COHORTS:
        matrix = {a: {b: 0 for b in _CLASSES} for a in _CLASSES}
        digest = hashlib.sha256((
            "LOOP2_CAUSAL_QUARANTINE_TRANSITIONS_V1\n" + dataset_id + "\n" +
            archive_sha256 + "\n" + str(n) + "\n" + str(split) + "\n" +
            cohort + "\n").encode("ascii"))
        changed = 0
        for i in range(16, n - 1):
            owner = ("development" if i + 1 < split - 16 else
                     "exploratory_later" if i >= split + 16 else None)
            if owner != cohort:
                continue
            start, end = i - 16, i + 1
            if broken[end + 1] - broken[start + 1]:
                a = b = "gap_or_segment"
            else:
                a, b = tuple(
                    "declared_duplicate_touched" if m[end + 1] - m[start]
                    else "quarantine_clean" for m in marks)
            matrix[a][b] += 1
            if a != b:
                changed += 1
                digest.update((str(i) + "|" +
                               bars[i].time.isoformat(timespec="seconds") + "|" +
                               bars[i + 1].time.isoformat(timespec="seconds") +
                               "|" + a + "|" + b + "\n").encode("ascii"))
        base_ref = baseline["cohorts"][cohort]
        new_ref = revised["cohorts"][cohort]
        total = sum(sum(row.values()) for row in matrix.values())
        if (total != base_ref["possible_sweep_indices"] or
                total != new_ref["possible_sweep_indices"]):
            raise RuntimeError("Paired candidate population mismatch")
        for phase in _CLASSES:
            if (sum(matrix[phase].values()) !=
                    base_ref["classes"][phase]["count"] or
                    sum(matrix[other][phase] for other in _CLASSES) !=
                    new_ref["classes"][phase]["count"]):
                raise RuntimeError("Paired quarantine class marginal mismatch")
        if any(matrix["gap_or_segment"][x] for x in _CLASSES[1:]) or any(
                matrix[x]["gap_or_segment"] for x in _CLASSES[1:]):
            raise RuntimeError("Source gap cannot change under M1 declaration")
        gained = matrix["declared_duplicate_touched"]["quarantine_clean"]
        lost = matrix["quarantine_clean"]["declared_duplicate_touched"]
        if changed != gained + lost:
            raise RuntimeError("Unexpected structural transition")
        result[cohort] = {
            "possible_sweep_indices": total,
            "baseline_by_revised_causal_class": matrix,
            "gained_clean_causal_windows": gained,
            "lost_clean_causal_windows": lost,
            "unchanged_clean_causal_windows": matrix["quarantine_clean"]["quarantine_clean"],
            "changed_causal_windows": changed,
            "changed_window_identity_sha256": digest.hexdigest(),
            "baseline_class_fingerprints": {
                k: base_ref["classes"][k]["source_local_window_identity_sha256"]
                for k in _CLASSES},
            "revised_class_fingerprints": {
                k: new_ref["classes"][k]["source_local_window_identity_sha256"]
                for k in _CLASSES},
        }
    return {
        "audit": "DECLARED_CAUSAL_QUARANTINE_TRANSITION_V1",
        "dataset_id": dataset_id,
        "source_declared_archive_sha256": archive_sha256,
        "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC",
        "frozen_split": "70_30_BY_ORIGINAL_BAR_INDEX_WITH_16_BAR_EMBARGO",
        "causal_window": "PRIOR16_SWEEP1_COMPLETED_CONFIRMATION1",
        "baseline_declared_m1_count": len(baseline_duplicate_m1_times),
        "revised_declared_m1_count": len(revised_duplicate_m1_times),
        "uses_future_entry_or_exit": False,
        "changed_counts_are_matched_trade_effects": False,
        "source_authenticated": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "cohorts": result,
    }
