"""Read-only source-local identities for causal CRT/ICT candidate windows.

No price, signal, future outcome, UTC mapping or broker quote is used in the
fingerprint. Digests are integrity comparisons, not authentication or secrecy.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from .offline_sweep_duplicate_bucket_sensitivity import (
    _parse_clock, _quarter_hour, audit_declared_duplicate_minutes,
)

_STEP = timedelta(minutes=15)
_PHASES = ("gap_or_segment", "declared_duplicate_touched", "quarantine_clean")
_COHORTS = ("development", "exploratory_later")


def audit_causal_cohort_identity(bars, duplicate_m1_times, *, dataset_id, archive_sha256):
    """Fingerprint exact eligible source-local 18-bar windows, not trade signals.

    Validation and the frozen 70/30+16 embargo cohort definition are delegated
    to the existing sensitivity audit. Only completed-confirmation information
    is used. All three phase populations are mutually exclusive.
    """
    parent = audit_declared_duplicate_minutes(
        bars, duplicate_m1_times, dataset_id=dataset_id,
        archive_sha256=archive_sha256)
    source = parent["causal_confirmation_window_coverage"]["cohorts"]
    touched = {_quarter_hour(_parse_clock(stamp))
               for stamp in duplicate_m1_times}
    touched.intersection_update(bar.time for bar in bars)
    n = len(bars)
    split = n * 7 // 10
    broken = [0] * (n + 1)
    duplicate = [0] * (n + 1)
    for j, bar in enumerate(bars):
        discontinuity = (j > 0 and (
            bar.segment != bars[j - 1].segment or
            bar.time - bars[j - 1].time != _STEP))
        broken[j + 1] = broken[j] + int(discontinuity)
        duplicate[j + 1] = duplicate[j] + int(bar.time in touched)
    digests = {}
    counts = {}
    for cohort in _COHORTS:
        digests[cohort] = {}
        counts[cohort] = {phase: 0 for phase in _PHASES}
        for phase in _PHASES:
            domain = ("LOOP2_SOURCE_LOCAL_CAUSAL_WINDOW_V1\n" +
                      dataset_id + "\n" + archive_sha256 + "\n" +
                      str(n) + "\n" + str(split) + "\n" +
                      cohort + "\n" + phase + "\n")
            digests[cohort][phase] = hashlib.sha256(domain.encode("ascii"))
    for i in range(16, n - 1):
        cohort = ("development" if i + 1 < split - 16 else
                  "exploratory_later" if i >= split + 16 else None)
        if cohort is None:
            continue
        start, end = i - 16, i + 1
        if broken[end + 1] - broken[start + 1]:
            phase = "gap_or_segment"
        elif duplicate[end + 1] - duplicate[start]:
            phase = "declared_duplicate_touched"
        else:
            phase = "quarantine_clean"
        counts[cohort][phase] += 1
        # Stable, unambiguous identity: source-local sweep index and the
        # completed sweep/confirmation timestamp pair. No future candles.
        identity = (str(i) + "|" +
                    bars[i].time.isoformat(timespec="seconds") + "|" +
                    bars[i + 1].time.isoformat(timespec="seconds") + "\n")
        digests[cohort][phase].update(identity.encode("ascii"))
    result = {}
    for cohort in _COHORTS:
        cell = source[cohort]
        if (counts[cohort]["gap_or_segment"] !=
                cell["confirmation_crosses_source_gap_or_segment"] or
                counts[cohort]["declared_duplicate_touched"] !=
                cell["declared_duplicate_touched_confirmation_windows"] or
                counts[cohort]["quarantine_clean"] !=
                cell["quarantine_clean_confirmation_windows"] or
                sum(counts[cohort].values()) != cell["possible_sweep_indices"]):
            raise RuntimeError("Causal cohort identity population mismatch")
        result[cohort] = {
            "possible_sweep_indices": cell["possible_sweep_indices"],
            "classes": {
                phase: {"count": counts[cohort][phase],
                        "source_local_window_identity_sha256":
                            digests[cohort][phase].hexdigest()}
                for phase in _PHASES
            },
        }
    return {
        "audit": "DECLARED_SOURCE_LOCAL_CAUSAL_WINDOW_IDENTITY_V1",
        "dataset_id": dataset_id,
        "source_declared_archive_sha256": archive_sha256,
        "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC",
        "window_definition": "PRIOR16_SWEEP1_COMPLETED_CONFIRMATION1",
        "cohort_split": "70_30_BY_ORIGINAL_BAR_INDEX_WITH_16_BAR_EMBARGO",
        "identity_includes_prices": False,
        "identity_includes_future_outcomes": False,
        "fingerprints_authenticate_source": False,
        "fingerprints_are_secrecy_protection": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "cohorts": result,
    }
