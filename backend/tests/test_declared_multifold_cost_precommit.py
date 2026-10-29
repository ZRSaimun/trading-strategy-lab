"""Synthetic-only regression tests: multi-fold cost scenario precommitment."""
import copy

import pytest

from app.declared_multifold_cost_precommit import (
    prepare_declared_multifold_cost_scenario_set_sha256 as prepare,
    require_declared_multifold_cost_scenario_set_sha256 as require,
)
from test_declared_holdout_fold_isolation import _valid

_COSTS = ("spread_extra_cash", "slippage_extra_cash",
          "commission_extra_cash", "financing_extra_cash", "fx_extra_cash")


def _scenario(fold, name, amount="0.0000"):
    return {
        "scenario_id": name,
        "adjustments": [
            dict(observation_id=row["observation_id"],
                 row_sha256=row["row_sha256"],
                 source_sha256=row["source_sha256"],
                 **{key: amount if key == "spread_extra_cash" else "0.0000"
                    for key in _COSTS})
            for row in fold["census"]
        ],
    }


def _folds():
    folds = _valid()
    for fold in folds:
        fold["scenarios"] = [
            _scenario(fold, "base"),
            _scenario(fold, "adverse", "0.2500"),
        ]
    return folds


def test_multifold_digest_matches_expected_and_preserves_inputs():
    folds = _folds()
    original = copy.deepcopy(folds)
    digest = prepare(folds)
    assert len(digest) == 64
    assert require(folds, digest) == digest
    assert folds == original


def test_scenario_and_row_order_are_canonical_within_each_fold():
    folds = _folds()
    digest = prepare(folds)
    for fold in folds:
        fold["scenarios"].reverse()
        for scenario in fold["scenarios"]:
            scenario["adjustments"].reverse()
    assert prepare(folds) == digest


@pytest.mark.parametrize("mutation", ["cost", "component", "row", "drop_fold",
                                       "drop_scenario", "new_scenario", "outcomes"])
def test_mutations_cannot_reuse_original_commitment(mutation):
    folds = _folds()
    original = prepare(folds)
    changed = copy.deepcopy(folds)
    if mutation == "cost":
        changed[1]["scenarios"][0]["adjustments"][0]["spread_extra_cash"] = "0.0001"
    elif mutation == "component":
        row = changed[1]["scenarios"][1]["adjustments"][0]
        row["spread_extra_cash"] = "0.0000"
        row["slippage_extra_cash"] = "0.2500"
    elif mutation == "row":
        changed[1]["scenarios"][0]["adjustments"][0]["row_sha256"] = "e" * 64
    elif mutation == "drop_fold":
        changed.pop()
    elif mutation == "drop_scenario":
        changed[1]["scenarios"].pop()
    elif mutation == "new_scenario":
        changed[1]["scenarios"].append(_scenario(changed[1], "unexpected"))
    else:
        changed[0]["outcomes"] = []
    if mutation in ("row", "drop_scenario", "new_scenario", "outcomes"):
        with pytest.raises(ValueError):
            require(changed, original)
    else:
        with pytest.raises(ValueError, match="mismatch"):
            require(changed, original)


def test_reordered_chronological_folds_fail_closed():
    folds = _folds()
    folds.reverse()
    with pytest.raises(ValueError, match="out-of-order"):
        prepare(folds)


def test_cross_fold_candidate_and_source_convention_changes_fail_closed():
    folds = _folds()
    folds[1]["manifest"]["candidate_config_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="source convention changed|candidate"):
        prepare(folds)


@pytest.mark.parametrize("expected", ["A" * 64, "0" * 63, None, 123])
def test_malformed_external_commitment_fails_closed(expected):
    with pytest.raises(ValueError, match="Invalid expected"):
        require(_folds(), expected)


def test_same_cost_total_relocated_between_rows_changes_commitment():
    folds = _folds()
    digest = prepare(folds)
    first, second = folds[2]["scenarios"][1]["adjustments"][:2]
    first["spread_extra_cash"] = "0.5000"
    second["spread_extra_cash"] = "0.0000"
    with pytest.raises(ValueError, match="mismatch"):
        require(folds, digest)


def test_two_folds_supported_but_one_fold_not_a_multifold_study():
    folds = _folds()
    assert len(prepare(folds[:2])) == 64
    with pytest.raises(ValueError, match="2..24"):
        prepare(folds[:1])
