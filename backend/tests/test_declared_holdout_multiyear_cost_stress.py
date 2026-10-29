"""Synthetic-only, source-disjoint multi-year holdout/cost stress regressions.

These tests do not authenticate source archives, preregistration, broker costs,
or market returns. They do not implement walk-forward model selection.
"""
import copy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.declared_holdout_cost_attribution import audit_declared_holdout_cost_attribution

from app.declared_holdout_release_gate import (
    audit_declared_holdout_release,
    prepare_declared_holdout_census_sha256,
    prepare_declared_holdout_manifest_sha256,
)

_DAY = 86400
_WINDOWS = ((2020, 2022), (2022, 2024), (2024, 2026))


def _utc(year):
    return int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())


def _fold(index):
    """Independent source identity and preregistered-looking DECLARED clocks."""
    first_year, last_year = _WINDOWS[index]
    start, end = _utc(first_year), _utc(last_year)
    source_sha = f"{index + 1:064x}"
    census = [
        dict(
            observation_id=f"obs-{i:03d}",
            row_sha256=f"{(index + 1) * 10000 + i:064x}",
            source_sha256=source_sha,
            decision_at_utc=start + 10 * i * _DAY,
            label_available_at_utc=start + (10 * i + 1) * _DAY,
        )
        for i in range(60)
    ]
    manifest = dict(
        study_id=f"synthetic-fold-{index}",
        candidate_id=f"fixed-candidate-{index}",
        candidate_config_sha256="b" * 64,
        selection_evidence_sha256="c" * 64,
        validation_end_at_utc=start - 6 * _DAY,
        selected_at_utc=start - 4 * _DAY,
        registered_at_utc=start - 3 * _DAY,
        holdout_start_at_utc=start,
        holdout_end_at_utc=end,
        embargo_seconds=_DAY,
        expected_holdout_count=len(census),
        holdout_census_sha256=prepare_declared_holdout_census_sha256(census),
        source=dict(
            provider="Synthetic", venue="Offline", instrument="XAUUSD-CFD",
            quote_side="BID", account_alias=f"sim-{index}",
            settlement_currency="GBP", utc_convention="UTC",
            archive_sha256=source_sha,
        ),
    )
    anchor = dict(
        manifest_sha256=prepare_declared_holdout_manifest_sha256(manifest),
        anchored_at_utc=start - 2 * _DAY,
        anchor_reference=f"declared-anchor-{index}",
        external_record_sha256="d" * 64,
    )
    outcomes = [
        dict(
            row,
            observed_at_utc=row["label_available_at_utc"] + _DAY,
            gross_cash="8.0000" if i % 2 == 0 else "-7.0000",
            spread_cash="0.2500", slippage_cash="0.1250",
            commission_cash="0.1250",
            financing_cash="0.2500" if i % 2 == 0 else "-0.2500",
            fx_cash="0.1250",
            receipt_sha256=f"{(index + 1) * 100000 + i:064x}",
        )
        for i, row in enumerate(census)
    ]
    return manifest, census, anchor, outcomes, end + 3 * _DAY


def _independent_net(outcomes):
    return sum(
        (
            Decimal(row["gross_cash"])
            - sum((Decimal(row[field]) for field in (
                "spread_cash", "slippage_cash", "commission_cash",
                "financing_cash", "fx_cash")), Decimal(0))
            for row in outcomes
        ),
        Decimal(0),
    )


@pytest.mark.parametrize("fold_index", range(len(_WINDOWS)))
def test_source_bound_multiyear_holdout_cost_stress(fold_index):
    """Three separate two-year synthetic windows; no fitted model or OOS claim."""
    baseline = _fold(fold_index)
    report = audit_declared_holdout_release(*baseline)
    assert report["observation_count"] == 60
    assert report["net_cash"] == format(_independent_net(baseline[3]), ".4f")
    assert report["net_cash"] == "-7.5000"
    assert report["max_observation_end_drawdown_cash"] is not None
    assert Decimal(report["max_observation_end_drawdown_cash"]) <= Decimal(
        report["max_receipt_time_ordering_drawdown_cash_upper_bound"])

    stressed = copy.deepcopy(baseline)
    for row in stressed[3]:
        row["spread_cash"] = "1.2500"
        row["slippage_cash"] = "0.6250"
        row["financing_cash"] = (
            "0.5000" if row["financing_cash"] == "0.2500" else "0.0000")
    stressed_report = audit_declared_holdout_release(*stressed)
    assert stressed_report["net_cash"] == format(_independent_net(stressed[3]), ".4f")
    assert Decimal(stressed_report["net_cash"]) == Decimal(report["net_cash"]) - Decimal("105.0000")
    assert stressed_report["net_cash"] == "-112.5000"
    for result in (report, stressed_report):
        assert result["broker_costs_verified"] is False
        assert result["holdout_untouched_independently_verified"] is False
        assert result["profitable_edge_verified"] is False
        assert result["may_execute_demo_order"] is False
        assert result["may_execute_real_order"] is False


def test_source_disjoint_folds_reject_cross_archive_receipts():
    first = list(_fold(0))
    second = _fold(1)
    first[3][0] = copy.deepcopy(second[3][0])
    with pytest.raises(ValueError, match="membership"):
        audit_declared_holdout_release(*first)


def test_source_digest_cannot_be_swapped_after_declared_census_freeze():
    data = list(_fold(2))
    data[0]["source"]["archive_sha256"] = _fold(1)[0]["source"]["archive_sha256"]
    data[2]["manifest_sha256"] = prepare_declared_holdout_manifest_sha256(data[0])
    with pytest.raises(ValueError, match="cross-source"):
        audit_declared_holdout_release(*data)


@pytest.mark.parametrize("fold_index", range(len(_WINDOWS)))
def test_randomized_adverse_costs_cannot_improve_drawdown(fold_index):
    """Pointwise higher declared costs cannot improve any receipt-cash drawdown.

    Invented overlapping receipt batches and signed financing are deliberate.
    This is a metamorphic arithmetic regression, not broker calibration or
    evidence of out-of-sample market returns.
    """
    from random import Random

    rng = Random(20261028 + fold_index)
    fields = ("spread_cash", "slippage_cash", "commission_cash",
              "financing_cash", "fx_cash")
    for _ in range(24):
        baseline = _fold(fold_index)
        # Overlapping trades can have receipts grouped into only three
        # UTC seconds, despite 60 distinct earlier decision timestamps.
        observed_base = max(row["label_available_at_utc"] for row in baseline[1]) + _DAY
        for i, row in enumerate(baseline[3]):
            row["observed_at_utc"] = observed_base + i % 3
            row["gross_cash"] = format(Decimal(rng.randint(-100000, 100000)) / 10000, ".4f")
            for field in fields:
                numerator = rng.randint(-3000 if field == "financing_cash" else 0, 3000)
                row[field] = format(Decimal(numerator) / 10000, ".4f")

        original = audit_declared_holdout_release(*baseline)
        stressed = copy.deepcopy(baseline)
        incremental = Decimal(0)
        for row in stressed[3]:
            for field in fields:
                increase = Decimal(rng.randint(0, 500)) / 10000
                row[field] = format(Decimal(row[field]) + increase, ".4f")
                incremental += increase
        higher_cost = audit_declared_holdout_release(*stressed)

        assert Decimal(higher_cost["net_cash"]) == (
            Decimal(original["net_cash"]) - incremental
        )
        assert Decimal(higher_cost["worst_observation_net_cash"]) <= Decimal(
            original["worst_observation_net_cash"])
        for field in ("max_observation_end_drawdown_cash",
                      "max_receipt_time_ordering_drawdown_cash_upper_bound"):
            assert Decimal(higher_cost[field]) >= Decimal(original[field])
        assert Decimal(higher_cost["max_observation_end_drawdown_cash"]) <= Decimal(
            higher_cost["max_receipt_time_ordering_drawdown_cash_upper_bound"])
        assert higher_cost["broker_costs_verified"] is False
        assert higher_cost["profitable_edge_verified"] is False
        assert higher_cost["may_execute_demo_order"] is False
        assert higher_cost["may_execute_real_order"] is False

        # Receipt input order must not create a fictitious within-second
        # execution ordering, nor alter the committed receipt digest.
        rng.shuffle(stressed[3])
        assert audit_declared_holdout_release(*stressed) == higher_cost


@pytest.mark.parametrize("fold_index", range(len(_WINDOWS)))
@pytest.mark.parametrize("field", ("spread_cash", "slippage_cash",
                                   "commission_cash", "fx_cash"))
def test_multiyear_cost_stress_rejects_negative_execution_charges(fold_index, field):
    """Negative execution charges must not be disguised as signed financing."""
    invalid = _fold(fold_index)
    invalid[3][0][field] = "-0.0001"
    with pytest.raises(ValueError, match="cash sign"):
        audit_declared_holdout_release(*invalid)


@pytest.mark.parametrize("fold_index", range(len(_WINDOWS)))
def test_multiyear_cost_attribution_reconciles_all_components(fold_index):
    """Three separate invented two-year sources; no broker or holdout proof."""
    data = _fold(fold_index)
    before = copy.deepcopy(data)
    report = audit_declared_holdout_cost_attribution(*data)
    assert report["observation_count"] == 60
    assert report["gross_cash"] == "30.0000"
    assert report["nonfinancing_charges_cash"] == "37.5000"
    assert report["financing_cash"] == "0.0000"
    assert report["financing_debit_cash"] == "7.5000"
    assert report["financing_credit_cash"] == "7.5000"
    assert report["net_cost_cash"] == "37.5000"
    assert report["net_cash"] == "-7.5000"
    assert data == before

    stressed = copy.deepcopy(data)
    for row in stressed[3]:
        row["spread_cash"] = "1.2500"
        row["slippage_cash"] = "0.6250"
        row["financing_cash"] = (
            "0.5000" if row["financing_cash"] == "0.2500" else "0.0000"
        )
    adverse = audit_declared_holdout_cost_attribution(*stressed)
    assert adverse["nonfinancing_charges_cash"] == "127.5000"
    assert adverse["financing_cash"] == "15.0000"
    assert adverse["financing_debit_cash"] == "15.0000"
    assert adverse["financing_credit_cash"] == "0.0000"
    assert adverse["net_cost_cash"] == "142.5000"
    assert adverse["net_cash"] == "-112.5000"
    assert Decimal(report["net_cash"]) - Decimal(adverse["net_cash"]) == Decimal("105.0000")
    for item in (report, adverse):
        assert item["source_bytes_independently_authenticated"] is False
        assert item["holdout_untouched_independently_verified"] is False
        assert item["broker_costs_verified"] is False
        assert item["profitable_edge_verified"] is False
        assert item["may_execute_demo_order"] is False
        assert item["may_execute_real_order"] is False
