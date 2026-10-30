"""Offline all-or-nothing release of preregistered *declared* multi-fold cost studies.

No archive bytes, external witness, broker quote or order interface is accessed.
A caller-supplied expected digest is not proof of independent preregistration.
"""
from __future__ import annotations

from decimal import Decimal, localcontext

from .declared_holdout_release_gate import _exact, _hash, _time
from .declared_holdout_row_cost_stress import audit_declared_holdout_row_cost_stress
from .declared_multifold_cost_precommit import (
    require_declared_multifold_cost_scenario_set_sha256,
)

_FOLD = {"manifest", "census", "scenarios", "anchor", "outcomes"}


def audit_declared_multifold_cost_release(
    folds, expected_scenario_set_sha256, release_at_utc
):
    """Release a complete frozen fold cohort, or withhold every outcome metric.

    Exact membership/cost commitments are checked before any outcomes are
    evaluated. Each fold must pass the existing source-bound receipt audit.
    If even one fold has fewer than 30 observations, *all* fold and cohort
    outcome-derived fields are suppressed, preventing favorable-fold leakage.
    """
    if type(folds) is not list or not 2 <= len(folds) <= 24:
        raise ValueError("Expected 2..24 declared release folds")
    declarations = []
    for fold in folds:
        _exact(fold, _FOLD, "multi-fold release")
        declarations.append({
            "manifest": fold["manifest"],
            "census": fold["census"],
            "scenarios": fold["scenarios"],
        })
    # Reject altered, missing, reordered or cross-source folds and costs
    # before inspecting any outcomes. The expected digest must have been
    # independently retained by the caller before outcome access.
    commitment = require_declared_multifold_cost_scenario_set_sha256(
        declarations, expected_scenario_set_sha256
    )
    if not _time(release_at_utc):
        raise ValueError("Invalid declared release clock")

    reports = []
    seen_receipts = set()
    for fold in folds:
        report = audit_declared_holdout_row_cost_stress(
            fold["manifest"], fold["census"], fold["anchor"],
            fold["outcomes"], release_at_utc, fold["scenarios"]
        )
        # A receipt reused under different archive/row identities must not
        # count twice as independent multi-year evidence.
        for outcome in fold["outcomes"]:
            receipt = outcome["receipt_sha256"]  # validated by release gate
            if receipt in seen_receipts:
                raise ValueError("Cross-fold outcome receipt reused")
            seen_receipts.add(receipt)
        reports.append(report)

    withheld = any(report["outcome_metrics_withheld"] for report in reports)
    names = sorted(scenario["scenario_id"] for scenario in folds[0]["scenarios"])
    summaries = []
    for index, report in enumerate(reports):
        scenario_by_id = {s["scenario_id"]: s for s in report["scenarios"]}
        summaries.append({
            "fold_index": index,
            "manifest_sha256": report["manifest_sha256"],
            "observation_count": report["observation_count"],
            "outcome_receipts_sha256": (
                None if withheld else report["outcome_receipts_sha256"]
            ),
            "baseline_net_cash": None if withheld else report["baseline_net_cash"],
            "scenario_stressed_net_cash": (
                None if withheld else {
                    name: scenario_by_id[name]["stressed_net_cash"] for name in names
                }
            ),
        })

    scenarios = None
    if not withheld:
        scenarios = []
        with localcontext() as ctx:
            ctx.prec = 80
            for name in names:
                rows = [
                    next(s for s in report["scenarios"] if s["scenario_id"] == name)
                    for report in reports
                ]
                nets = [Decimal(row["stressed_net_cash"]) for row in rows]
                extras = [Decimal(row["extra_cost_cash"]) for row in rows]
                scenarios.append({
                    "scenario_id": name,
                    "stressed_net_cash": format(sum(nets, Decimal(0)), ".4f"),
                    "additional_cost_cash": format(sum(extras, Decimal(0)), ".4f"),
                    "worst_fold_stressed_net_cash": format(min(nets), ".4f"),
                    "negative_net_fold_count": sum(net < 0 for net in nets),
                    "positive_net_fold_count": sum(net > 0 for net in nets),
                    # Fixed, preregistered fold membership is preserved.
                    # These are leave-one-fold-out diagnostics, NOT a new
                    # candidate selection or a permission to omit a fold.
                    "leave_one_fold_out_min_net_cash": format(
                        sum(nets, Decimal(0)) - max(nets), ".4f"
                    ),
                    "leave_one_fold_out_max_net_cash": format(
                        sum(nets, Decimal(0)) - min(nets), ".4f"
                    ),
                    "any_leave_one_fold_out_net_nonpositive": any(
                        sum(nets, Decimal(0)) - net <= 0 for net in nets
                    ),
                })
    return {
        "protocol": "declared-multifold-cost-release-v1",
        "status": ("WITHHELD_INCOMPLETE_FOLD_SAMPLE" if withheld
                   else "DECLARED_EVALUATION_ONLY"),
        "scenario_set_sha256": commitment,
        "fold_count": len(folds),
        "observation_count": sum(len(fold["census"]) for fold in folds),
        "outcome_metrics_withheld": withheld,
        "baseline_net_cash": (
            None if withheld else format(
                sum((Decimal(r["baseline_net_cash"]) for r in reports),
                    Decimal(0)), ".4f"
            )
        ),
        "scenarios": scenarios,
        "folds": summaries,
        "external_precommitment_independently_authenticated": False,
        "source_bytes_independently_authenticated": False,
        "holdout_untouched_independently_verified": False,
        "broker_costs_verified": False,
        "profitable_edge_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "All manifests, receipts, anchors, costs and expected digest are "
                   "caller-declared. This cannot prove independent registration, "
                   "unseen archives, no prior holdout peeks, executable financing, "
                   "spread/slippage, margin or intraperiod account-equity risk. "
                   "No trading permission or profitable edge is established.",
    }
