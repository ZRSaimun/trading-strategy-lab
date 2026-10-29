"""Outcome-free preflight for caller-declared holdout row-cost commitments.

This validates only supplied identities and cash strings. A digest is not
external registration, source authentication, or permission to trade.
"""
from __future__ import annotations

import hmac

from .declared_holdout_release_gate import (
    _exact, _hash, _id, _money, _sha, _validate_census, _validate_manifest,
)
from .declared_holdout_row_cost_stress import _COSTS, _ROW, _SCENARIO


def prepare_declared_holdout_row_cost_scenario_set_sha256(manifest, census, scenarios):
    """Commit complete declared costs before supplying any outcome receipts."""
    _validate_manifest(manifest)
    _validate_census(manifest, census)
    if type(scenarios) is not list or not 1 <= len(scenarios) <= 8:
        raise ValueError("Expected one to eight declared row-cost scenarios")
    by_id = {row["observation_id"]: row for row in census}
    names = set()
    canonical = []
    for scenario in scenarios:
        _exact(scenario, _SCENARIO, "row-cost scenario")
        name = scenario["scenario_id"]
        if not _id(name) or name in names:
            raise ValueError("Invalid or duplicate row-cost scenario ID")
        names.add(name)
        adjustments = scenario["adjustments"]
        if type(adjustments) is not list or len(adjustments) != len(census):
            raise ValueError("Row-cost scenario must cover every holdout observation")
        seen = set()
        for adjustment in adjustments:
            _exact(adjustment, _ROW, "row-cost adjustment")
            key = adjustment["observation_id"]
            original = by_id.get(key) if _id(key) else None
            if (original is None or key in seen or
                    adjustment["row_sha256"] != original["row_sha256"] or
                    adjustment["source_sha256"] != original["source_sha256"]):
                raise ValueError("Duplicate, missing or cross-source row-cost identity")
            seen.add(key)
            for field in _COSTS:
                _money(adjustment[field], nonnegative=True)
        if seen != set(by_id):
            raise ValueError("Incomplete row-cost population")
        canonical.append({
            "scenario_id": name,
            "adjustments": sorted(adjustments, key=lambda row: row["observation_id"]),
        })
    return _hash({
        "protocol": "declared-holdout-row-cost-scenario-set-v1",
        "manifest_sha256": _hash(manifest),
        "holdout_census_sha256": manifest["holdout_census_sha256"],
        "scenarios": sorted(canonical, key=lambda row: row["scenario_id"]),
    })


def require_declared_holdout_row_cost_scenario_set_sha256(
    manifest, census, scenarios, expected_sha256
):
    """Fail closed on a mismatched *declared* digest; does not authenticate its origin."""
    if not _sha(expected_sha256):
        raise ValueError("Invalid expected scenario-set SHA-256")
    actual = prepare_declared_holdout_row_cost_scenario_set_sha256(
        manifest, census, scenarios
    )
    if not hmac.compare_digest(actual, expected_sha256):
        raise ValueError("Declared row-cost scenario-set commitment mismatch")
    return actual
