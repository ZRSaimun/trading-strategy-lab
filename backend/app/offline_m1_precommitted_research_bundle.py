"""Fail-closed, precommitted bundle of disconnected exploratory M1 auditors.

This reconciles *declared* research outputs, not independent evidence that a
pre-outcome commitment existed, that data are authentic, or that a trade works.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib

from app.offline_m1_cohort_precommitment import require_m1_precommitted_cohort
from app.offline_m1_archive_robustness import audit_m1_archive_robustness
from app.offline_m1_archive_deletion_stress import audit_m1_archive_deletion_stress
from app.offline_m1_paired_direction_cost_falsification import (
    audit_m1_paired_direction_cost_falsification,
)
from app.offline_m1_cost_frontier import audit_m1_cost_frontier
from app.offline_m1_multi_archive_census import COSTS, POLICY, _canonical

SCHEMA = "exploratory-m1-precommitted-research-bundle-v1"
TOLERANCE = Decimal("0.000002")


def _index(groups):
    if not isinstance(groups, list):
        raise ValueError("Malformed research group census")
    indexed = {}
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Malformed research group")
        key = (group.get("instrument"), group.get("provider"))
        if not all(isinstance(part, str) for part in key) or key in indexed:
            raise ValueError("Duplicate or invalid source cohort")
        indexed[key] = group
    return indexed


def _close(a, b):
    if a is None or b is None:
        return a is b
    return abs(Decimal(str(a)) - Decimal(str(b))) <= TOLERANCE


def audit_m1_precommitted_research_bundle(reports, expected_source_cohort_sha256):
    """Reconcile all existing descriptive audits against one external digest.

    This gate intentionally has no "pass to trade" state. A caller must obtain
    the expected digest from a separately retained pre-outcome record; this
    function cannot attest to the record's existence or timestamp.
    """
    committed = require_m1_precommitted_cohort(reports, expected_source_cohort_sha256)
    robustness = audit_m1_archive_robustness(reports)
    deletion = audit_m1_archive_deletion_stress(reports)
    paired = audit_m1_paired_direction_cost_falsification(reports)
    frontier = audit_m1_cost_frontier(reports)

    if (robustness["source_census_sha256"] != committed["source_census_sha256"]
            or deletion["source_robustness_sha256"] != robustness["research_sha256"]
            or paired["source_robustness_sha256"] != robustness["research_sha256"]
            or frontier["source_robustness_sha256"] != robustness["research_sha256"]):
        raise ValueError("Research lineage hashes disagree")
    audits = (robustness, deletion, paired, frontier)
    if any(audit["policy"] != POLICY or audit["cost_grid_bps"] != list(COSTS)
           or audit["trade_authorized"] is not False
           or audit["research_only"] is not True for audit in audits):
        raise ValueError("Research policy, cost grid or safety flags disagree")

    census = _index(committed["groups"])
    indexed = [_index(audit["groups"]) for audit in audits]
    if any(set(other) != set(census) for other in indexed):
        raise ValueError("Source cohort coverage differs between auditors")

    result_groups = []
    for key in sorted(census):
        base = census[key]
        robust, deleted, mirror, costs = (groups[key] for groups in indexed)
        count = base["archive_count"]
        n = base["evaluated_count"]
        if any(g["archive_count"] != count for g in (robust, deleted, mirror, costs)):
            raise ValueError("Archive population differs between auditors")
        if any(g["evaluated_outcome_count"] != n
               for g in (robust, deleted, mirror, costs)):
            raise ValueError("Evaluated population differs between auditors")
        if any(g["archive_sha256"] != base["archive_sha256"]
               for g in (robust, mirror, costs)):
            raise ValueError("Archive identities differ between auditors")

        incomplete = base["status"] == "INCOMPLETE_ARCHIVE_COVERAGE"
        if incomplete:
            expected_robust_status = ("NO_EVALUATED_ARCHIVES" if n == 0
                                      else "INCOMPLETE_ARCHIVE_COVERAGE")
            if (robust["status"] != expected_robust_status
                    or any(g["status"] != "INCOMPLETE_ARCHIVE_COVERAGE"
                           for g in (deleted, mirror, costs))
                    or any(base["weighted_mean_net_bps_by_illustrative_cost"][str(c)] is not None
                           for c in COSTS)
                    or costs["break_even_roundtrip_cost_intervals_bps"] is not None):
                raise ValueError("Incomplete archive coverage leaked performance")
        elif base["status"] != "DESCRIPTIVE_EXPLORATORY_ONLY":
            raise ValueError("Unexpected source census status")

        for c in COSTS:
            label = str(c)
            gross_net = base["weighted_mean_net_bps_by_illustrative_cost"][label]
            robust_net = robust["scenarios_by_illustrative_cost_bps"][label]["trade_weighted_net_bps"]
            mirrored_net = mirror["scenarios_by_illustrative_cost_bps"][label]["fixed_direction_net_bps"]
            if not (_close(gross_net, robust_net) and _close(gross_net, mirrored_net)):
                raise ValueError("Auditor fixed-direction means disagree")
            if incomplete:
                if (robust_net is not None or mirrored_net is not None
                        or mirror["scenarios_by_illustrative_cost_bps"][label]["hindsight_per_archive_oracle_net_bps"] is not None):
                    raise ValueError("Incomplete source leaked directional results")
            else:
                bounds = costs["break_even_roundtrip_cost_intervals_bps"]["fixed_direction"]
                gross = Decimal(str(gross_net)) + Decimal(c)
                if not (Decimal(bounds["lower_bps"]) - TOLERANCE <= gross
                        <= Decimal(bounds["upper_bps"]) + TOLERANCE):
                    raise ValueError("Cost-frontier rounding interval disagrees")
                one = deleted["deletion_by_whole_archive_count"]["1"]
                if count >= 2:
                    stress = one["scenarios_by_illustrative_cost_bps"][label]
                    reference = robust["scenarios_by_illustrative_cost_bps"][label]
                    if not (_close(stress["min_net_bps"], reference["leave_one_archive_out_min_net_bps"])
                            and _close(stress["max_net_bps"], reference["leave_one_archive_out_max_net_bps"])):
                        raise ValueError("Whole-archive deletion auditors disagree")

        result_groups.append({
            "instrument": key[0],
            "provider": key[1],
            "archive_count": count,
            "evaluated_outcome_count": n,
            "status": ("INCOMPLETE_ARCHIVE_COVERAGE" if incomplete
                       else "DESCRIPTIVE_RECONCILED_ONLY"),
            "fixed_direction_net_bps_at_5_illustrative": (
                None if incomplete else base["weighted_mean_net_bps_by_illustrative_cost"]["5"]
            ),
            "fixed_direction_mean_nonpositive_at_5_illustrative": (
                None if incomplete else base["weighted_mean_net_bps_by_illustrative_cost"]["5"] <= 0
            ),
        })

    body = {
        "schema": SCHEMA, "policy": POLICY,
        "external_expected_source_cohort_sha256": expected_source_cohort_sha256,
        "source_census_sha256": committed["source_census_sha256"],
        "robustness_sha256": robustness["research_sha256"],
        "deletion_sha256": deletion["research_sha256"],
        "paired_direction_sha256": paired["research_sha256"],
        "cost_frontier_sha256": frontier["research_sha256"],
        "groups": result_groups,
    }
    return {
        **body,
        "research_sha256": hashlib.sha256(_canonical(body).encode("ascii")).hexdigest(),
        "research_only": True, "trade_authorized": False,
        "verified_profitability": False, "protected_holdout": False,
        "independent_precommitment_verified": False,
        "source_authenticity_verified": False, "executable_quotes_verified": False,
        "statistical_significance_verified": False,
        "warning": (
            "Reconciled self-hashed exploratory receipts only. External pre-outcome "
            "registration was not independently verified. No authenticated prices, "
            "source UTC, executable spreads, financing, protected holdout, "
            "statistical significance, live signal or broker permission."
        ),
    }
