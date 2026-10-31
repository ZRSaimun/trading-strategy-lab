"""Outcome-free multi-fold cost precommitment for source-disjoint holdouts.

Only caller-declared identities and cost strings are examined. This is not
independent preregistration, broker calibration or a trading authorization.
"""
from __future__ import annotations

import hmac

from .declared_holdout_cost_precommit import (
    prepare_declared_holdout_row_cost_scenario_set_sha256,
)
from .declared_holdout_fold_isolation import audit_declared_holdout_fold_isolation
from .declared_holdout_release_gate import _hash, _sha


def prepare_declared_multifold_cost_scenario_set_sha256(folds):
    """Bind every chronological fold and its complete cost scenarios, before outcomes.

    The declared fold-isolation audit rejects reused source archives/rows,
    changed candidate/source conventions, overlapping windows and label
    embargo violations. Scenario IDs must be present in *every* fold; no
    favorable subset may be silently substituted after a registered digest.
    """
    if type(folds) is not list or not 2 <= len(folds) <= 24:
        raise ValueError("Expected 2..24 declared chronological cost folds")
    for fold in folds:
        if type(fold) is not dict or set(fold) != {"manifest", "census", "scenarios"}:
            raise ValueError("Invalid exact cost-fold schema (outcomes forbidden)")
    audit_declared_holdout_fold_isolation([
        {"manifest": fold["manifest"], "census": fold["census"]}
        for fold in folds
    ])
    scenario_ids = None
    commitments = []
    for fold in folds:
        scenarios = fold["scenarios"]
        # Validate all costs, source/row identities and complete observation
        # coverage even if a later fold's scenario names do not match.
        digest = prepare_declared_holdout_row_cost_scenario_set_sha256(
            fold["manifest"], fold["census"], scenarios
        )
        ids = frozenset(scenario["scenario_id"] for scenario in scenarios)
        if scenario_ids is None:
            scenario_ids = ids
        elif ids != scenario_ids:
            raise ValueError("Every chronological fold must declare the same scenario IDs")
        commitments.append({
            "manifest_sha256": _hash(fold["manifest"]),
            "holdout_census_sha256": fold["manifest"]["holdout_census_sha256"],
            "scenario_set_sha256": digest,
        })
    return _hash({
        "protocol": "declared-multifold-cost-scenario-set-v1",
        "fold_count": len(folds),
        "scenario_ids": sorted(scenario_ids),
        # Chronological order is deliberately preserved; reordering folds
        # must not produce the same preregistered research commitment.
        "folds": commitments,
    })


def require_declared_multifold_cost_scenario_set_sha256(folds, expected_sha256):
    """Compare against an independently retained digest, never a fresh local one."""
    if not _sha(expected_sha256):
        raise ValueError("Invalid expected multi-fold scenario-set SHA-256")
    actual = prepare_declared_multifold_cost_scenario_set_sha256(folds)
    if not hmac.compare_digest(actual, expected_sha256):
        raise ValueError("Declared multi-fold scenario-set commitment mismatch")
    return actual
