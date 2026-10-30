"""Synthetic-only all-or-nothing multi-fold cost release regressions."""
import copy

import pytest

from app.declared_holdout_release_gate import (
    _hash, prepare_declared_holdout_census_sha256,
)
from app.declared_multifold_cost_precommit import (
    prepare_declared_multifold_cost_scenario_set_sha256 as prepare,
)
from app.declared_multifold_cost_release import (
    audit_declared_multifold_cost_release as audit,
)
from test_declared_multifold_cost_precommit import _folds


def _study():
    folds = _folds()
    for index, fold in enumerate(folds):
        manifest = fold["manifest"]
        fold["anchor"] = {
            "manifest_sha256": _hash(manifest),
            "anchored_at_utc": manifest["registered_at_utc"] + 3600,
            "anchor_reference": f"declared-witness-{index}",
            "external_record_sha256": f"{9000 + index:064x}",
        }
        fold["outcomes"] = [
            dict(row, observed_at_utc=row["label_available_at_utc"] + 3600,
                 gross_cash="1.0000", spread_cash="0.0000",
                 slippage_cash="0.0000", commission_cash="0.0000",
                 financing_cash="0.0000", fx_cash="0.0000",
                 receipt_sha256=f"{(index + 1) * 10000 + i + 1:064x}")
            for i, row in enumerate(fold["census"])
        ]
    release = max(f["manifest"]["holdout_end_at_utc"] for f in folds) + 86400
    return folds, release


def _commit(folds):
    return prepare([
        {k: fold[k] for k in ("manifest", "census", "scenarios")}
        for fold in folds
    ])


def test_three_source_disjoint_folds_reconcile_costs_and_preserve_inputs():
    folds, release = _study()
    original = copy.deepcopy(folds)
    result = audit(folds, _commit(folds), release)
    assert folds == original
    assert result["status"] == "DECLARED_EVALUATION_ONLY"
    assert result["fold_count"] == 3
    assert result["observation_count"] == 120
    assert result["baseline_net_cash"] == "120.0000"
    by_name = {row["scenario_id"]: row for row in result["scenarios"]}
    assert by_name["base"]["stressed_net_cash"] == "120.0000"
    assert by_name["adverse"]["stressed_net_cash"] == "90.0000"
    assert by_name["adverse"]["additional_cost_cash"] == "30.0000"
    assert by_name["adverse"]["worst_fold_stressed_net_cash"] == "30.0000"
    assert by_name["adverse"]["negative_net_fold_count"] == 0
    assert len(result["folds"]) == 3
    assert all(f["outcome_receipts_sha256"] for f in result["folds"])
    for key in ("external_precommitment_independently_authenticated",
                "source_bytes_independently_authenticated",
                "holdout_untouched_independently_verified",
                "broker_costs_verified", "profitable_edge_verified",
                "may_execute_demo_order", "may_execute_real_order"):
        assert result[key] is False


def test_outcome_order_and_cost_order_do_not_change_result():
    folds, release = _study()
    digest = _commit(folds)
    original = audit(folds, digest, release)
    for fold in folds:
        fold["outcomes"].reverse()
        fold["scenarios"].reverse()
        for scenario in fold["scenarios"]:
            scenario["adjustments"].reverse()
    assert audit(folds, digest, release) == original


@pytest.mark.parametrize("change", ["cost", "archive", "missing_fold",
                                      "extra_fold_key", "missing_scenario"])
def test_precommitted_declarations_fail_closed(change):
    folds, release = _study()
    digest = _commit(folds)
    if change == "cost":
        folds[1]["scenarios"][1]["adjustments"][0]["spread_extra_cash"] = "0.2600"
    elif change == "archive":
        folds[1]["manifest"]["source"]["archive_sha256"] = "a" * 64
    elif change == "missing_fold":
        folds.pop()
    elif change == "extra_fold_key":
        folds[0]["unregistered_outcome"] = "1"
    else:
        folds[0]["scenarios"].pop()
    with pytest.raises(ValueError):
        audit(folds, digest, release)


def test_reused_receipt_across_distinct_folds_is_rejected():
    folds, release = _study()
    digest = _commit(folds)
    folds[1]["outcomes"][0]["receipt_sha256"] = folds[0]["outcomes"][0]["receipt_sha256"]
    with pytest.raises(ValueError, match="Cross-fold outcome receipt"):
        audit(folds, digest, release)


def test_missing_or_unmatured_outcome_fails_whole_cohort():
    folds, release = _study()
    digest = _commit(folds)
    folds[1]["outcomes"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        audit(folds, digest, release)
    folds, release = _study()
    digest = _commit(folds)
    folds[2]["outcomes"][0]["observed_at_utc"] = release + 1
    with pytest.raises(ValueError, match="Unobserved"):
        audit(folds, digest, release)


def test_single_underpowered_fold_suppresses_all_fold_and_cohort_outcomes():
    folds, release = _study()
    fold = folds[1]
    fold["census"] = fold["census"][:29]
    fold["manifest"]["expected_holdout_count"] = 29
    fold["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(fold["census"])
    )
    for scenario in fold["scenarios"]:
        scenario["adjustments"] = scenario["adjustments"][:29]
    fold["outcomes"] = fold["outcomes"][:29]
    fold["anchor"]["manifest_sha256"] = _hash(fold["manifest"])
    result = audit(folds, _commit(folds), release)
    assert result["observation_count"] == 109
    assert result["status"] == "WITHHELD_INCOMPLETE_FOLD_SAMPLE"
    assert result["outcome_metrics_withheld"] is True
    assert result["baseline_net_cash"] is None
    assert result["scenarios"] is None
    assert all(row["outcome_receipts_sha256"] is None and
               row["baseline_net_cash"] is None and
               row["scenario_stressed_net_cash"] is None
               for row in result["folds"])


def test_release_clock_must_cover_all_folds():
    folds, release = _study()
    with pytest.raises(ValueError, match="premature"):
        audit(folds, _commit(folds), folds[-1]["manifest"]["holdout_start_at_utc"])


def test_cross_fold_source_currency_mismatch_is_not_aggregated():
    folds, release = _study()
    folds[1]["manifest"]["source"]["settlement_currency"] = "USD"
    folds[1]["anchor"]["manifest_sha256"] = _hash(folds[1]["manifest"])
    with pytest.raises(ValueError, match="source convention changed"):
        audit(folds, "0" * 64, release)
