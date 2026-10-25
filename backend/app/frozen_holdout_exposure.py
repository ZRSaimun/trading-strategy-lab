"""Conservative full-horizon exposure census for frozen chronological M1 cohorts.

Potential positions remain open until their declared horizon ends regardless of
retrospective stop/target outcomes. This never chooses an overlap-free subset,
models capital-constrained fills, or licenses executable trading.
"""
from collections import defaultdict
from datetime import datetime, timezone
import heapq

from app.frozen_bracket_population import audit_frozen_bracket_population
from app.frozen_chronological_holdout import audit_frozen_chronological_holdout

_MAX_CLOCK = 8640000000


def _withheld(base, reason):
    return dict(
        protocol="frozen-m1-holdout-exposure-v1",
        status="WITHHELD_INCOMPLETE_OR_LEAKAGE_OR_INSUFFICIENT",
        reason=reason,
        cutoff_utc_minute=base["cutoff_utc_minute"],
        embargo_minutes=base["embargo_minutes"],
        eligible_signals=base["eligible_signals"],
        declared_excluded_signals=base["declared_excluded_signals"],
        training_signals=base["training_signals"],
        holdout_signals=base["holdout_signals"],
        potential_overlap_pairs=None,
        training_potential_overlap_pairs=None,
        holdout_potential_overlap_pairs=None,
        cost_scenarios=[],
        independent_preregistration_verified=False,
        source_authenticated=False,
        executable_broker_fills=False,
        capital_feasible_returns_verified=False,
        verified_profitability=False,
        may_execute_order=False,
    )


def audit_frozen_holdout_exposure(
    manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes,
    *, sample_limit=20
):
    """Count all potential full-horizon overlapping pairs by frozen cohort.

    Intervals are half-open [signal_at + 60, signal_at + 60 + horizon*60).
    All signals, including historical losses and ambiguous stop/target outcomes,
    remain in the census. No future exit timestamp shortens an interval.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid bounded overlap sample limit")
    base = audit_frozen_chronological_holdout(
        manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes
    )
    if base["status"] != "DESCRIPTIVE_CHRONOLOGICAL_COMPARISON_ONLY":
        return _withheld(base, "Upstream chronological holdout withheld: " + base["reason"])

    audited = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcome = audited["outcome_audit"]
    if (audited["manifest_sha256"] != base["manifest_sha256"]
            or audited["eligible_signals"] != base["eligible_signals"]
            or audited["declared_excluded_signals"] != 0
            or outcome["status"] != "DESCRIPTIVE_BOUNDS_ONLY"
            or outcome["counts"]["CENSORED"] != 0):
        raise ValueError("Inconsistent complete frozen chronological population")

    frozen = manifest["eligible_signals"]
    if len(frozen) != len(outcome["paths"]):
        raise ValueError("Changed frozen outcome population")
    if {x["path_id"] for x in frozen} != {x["path_id"] for x in outcome["paths"]}:
        raise ValueError("Changed frozen outcome membership")

    horizon = manifest["source"]["horizon_minutes"] * 60
    ordered = sorted(frozen, key=lambda row: (row["signal_at"], row["path_id"]))
    active = []  # (potential end, path ID, cohort)
    active_cohorts = [0, 0]
    pair_counts = [0, 0]
    affected = [set(), set()]
    peaks = [0, 0]
    active_weeks_with_overlap = [set(), set()]
    total_pairs = 0
    cross_pairs = 0
    overall_peak = 0
    examples = []
    previous = None

    for row in ordered:
        path_id = row["path_id"]
        start = row["signal_at"] + 60
        end = start + horizon
        if end > _MAX_CLOCK:
            raise ValueError("Potential exposure horizon exceeds supported clock")
        cohort = int(row["signal_at"] >= cutoff_utc_minute)
        while active and active[0][0] <= start:
            _, _, expired_cohort = heapq.heappop(active)
            active_cohorts[expired_cohort] -= 1
        if sum(active_cohorts) != len(active):
            raise ValueError("Internal active exposure accounting mismatch")
        overlapping = len(active)
        total_pairs += overlapping
        pair_counts[cohort] += active_cohorts[cohort]
        cross_pairs += active_cohorts[1 - cohort]
        if overlapping:
            # Every interval has the same horizon, so the immediately preceding
            # start is active whenever any older interval is still active.
            if previous is None or previous[1] <= start:
                raise ValueError("Internal fixed-horizon adjacency mismatch")
            prior_id, _, prior_cohort, prior_signal = previous
            affected[cohort].add(path_id)
            affected[prior_cohort].add(prior_id)
            active_weeks_with_overlap[cohort].add(
                datetime.fromtimestamp(row["signal_at"], timezone.utc).isocalendar()[:2]
            )
            active_weeks_with_overlap[prior_cohort].add(
                datetime.fromtimestamp(prior_signal, timezone.utc).isocalendar()[:2]
            )
            if len(examples) < sample_limit:
                examples.append(dict(
                    earlier_path_id=prior_id,
                    later_path_id=path_id,
                    later_entry_at=start,
                    cohort="HOLDOUT" if cohort else "TRAINING",
                ))
        heapq.heappush(active, (end, path_id, cohort))
        active_cohorts[cohort] += 1
        peaks[cohort] = max(peaks[cohort], active_cohorts[cohort])
        overall_peak = max(overall_peak, len(active))
        previous = (path_id, end, cohort, row["signal_at"])

    if cross_pairs:
        raise ValueError("Training/holdout potential exposures overlap despite embargo")
    if sum(pair_counts) != total_pairs:
        raise ValueError("Inconsistent cohort overlap accounting")
    if (sum(row["signal_at"] < cutoff_utc_minute for row in ordered) != base["training_signals"]
            or sum(row["signal_at"] >= cutoff_utc_minute for row in ordered) != base["holdout_signals"]):
        raise ValueError("Changed chronological cohort membership")

    return dict(
        protocol="frozen-m1-holdout-exposure-v1",
        status="DESCRIPTIVE_POTENTIAL_EXPOSURE_ONLY",
        manifest_sha256=audited["manifest_sha256"],
        cutoff_utc_minute=cutoff_utc_minute,
        embargo_minutes=embargo_minutes,
        eligible_signals=len(ordered),
        declared_excluded_signals=0,
        training_signals=base["training_signals"],
        holdout_signals=base["holdout_signals"],
        assumed_full_horizon_minutes=manifest["source"]["horizon_minutes"],
        potential_overlap_pairs=total_pairs,
        training_potential_overlap_pairs=pair_counts[0],
        holdout_potential_overlap_pairs=pair_counts[1],
        cross_cohort_potential_overlap_pairs=cross_pairs,
        training_signals_affected_by_potential_overlap=len(affected[0]),
        holdout_signals_affected_by_potential_overlap=len(affected[1]),
        training_active_utc_weeks_with_potential_overlap=len(active_weeks_with_overlap[0]),
        holdout_active_utc_weeks_with_potential_overlap=len(active_weeks_with_overlap[1]),
        maximum_potential_concurrent_signals=overall_peak,
        training_maximum_potential_concurrent_signals=peaks[0],
        holdout_maximum_potential_concurrent_signals=peaks[1],
        overlap_free_under_full_horizon=total_pairs == 0,
        adjacent_overlap_samples=examples,
        sample_limit=sample_limit,
        cost_scenarios=base["cost_scenarios"],
        independent_preregistration_verified=False,
        source_authenticated=False,
        executable_broker_fills=False,
        capital_feasible_returns_verified=False,
        verified_profitability=False,
        may_execute_order=False,
        warning=(
            "Retrospective descriptive holdout and potential exposure census only. "
            "Full-horizon potential concurrency deliberately ignores earlier actual exits; "
            "all original signals and losses remain in mean R. These means are not "
            "capital-constrained, compounded, independent or executable portfolio returns. "
            "Self-declared manifest/cutoff do not prove a sealed holdout, source rights "
            "or broker spreads/slippage/commissions/financing. No profitable edge verified."
        ),
    )
