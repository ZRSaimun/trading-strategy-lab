"""Synthetic-only cost attribution regressions; no market or broker data."""
import copy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.declared_holdout_release_gate import (
    prepare_declared_holdout_census_sha256,
    prepare_declared_holdout_manifest_sha256,
)
from app.declared_holdout_cost_attribution import (
    audit_declared_holdout_cost_attribution,
)

_DAY = 86400


def _fixture(count=30):
    start = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    source_sha = "a" * 64
    census = [
        {
            "observation_id": f"obs-{i:03d}",
            "row_sha256": f"{i + 1:064x}",
            "source_sha256": source_sha,
            "decision_at_utc": start + (i + 1) * _DAY,
            "label_available_at_utc": start + (i + 2) * _DAY,
        }
        for i in range(count)
    ]
    manifest = {
        "study_id": "offline-cost-study",
        "candidate_id": "fixed-candidate",
        "candidate_config_sha256": "b" * 64,
        "selection_evidence_sha256": "c" * 64,
        "validation_end_at_utc": start - 6 * _DAY,
        "selected_at_utc": start - 4 * _DAY,
        "registered_at_utc": start - 3 * _DAY,
        "holdout_start_at_utc": start,
        "holdout_end_at_utc": start + 100 * _DAY,
        "embargo_seconds": _DAY,
        "expected_holdout_count": count,
        "holdout_census_sha256": prepare_declared_holdout_census_sha256(census),
        "source": {
            "provider": "Synthetic", "venue": "Offline",
            "instrument": "XAUUSD-CFD", "quote_side": "BID",
            "account_alias": "paper-only", "settlement_currency": "GBP",
            "utc_convention": "UTC", "archive_sha256": source_sha,
        },
    }
    anchor = {
        "manifest_sha256": prepare_declared_holdout_manifest_sha256(manifest),
        "anchored_at_utc": start - 2 * _DAY,
        "anchor_reference": "synthetic-anchor",
        "external_record_sha256": "d" * 64,
    }
    outcomes = [
        {
            **row, "observed_at_utc": row["label_available_at_utc"] + 1,
            "gross_cash": "2.0000", "spread_cash": "0.1000",
            "slippage_cash": "0.0500", "commission_cash": "0.0250",
            "fx_cash": "0.0250",
            "financing_cash": "0.1000" if i % 2 else "-0.1000",
            "receipt_sha256": f"{i + 1000:064x}",
        }
        for i, row in enumerate(census)
    ]
    return manifest, census, anchor, outcomes, start + 101 * _DAY


def _audit(data):
    return audit_declared_holdout_cost_attribution(*data)


def test_signed_financing_and_components_reconcile_exactly():
    data = _fixture()
    before = copy.deepcopy(data)
    result = _audit(data)
    assert result["status"] == "DECLARED_EVALUATION_ONLY"
    assert result["observation_count"] == 30
    assert result["gross_cash"] == "60.0000"
    assert result["spread_cash"] == "3.0000"
    assert result["slippage_cash"] == "1.5000"
    assert result["commission_cash"] == "0.7500"
    assert result["fx_cash"] == "0.7500"
    assert result["financing_cash"] == "0.0000"
    assert result["financing_debit_cash"] == "1.5000"
    assert result["financing_credit_cash"] == "1.5000"
    assert result["nonfinancing_charges_cash"] == "6.0000"
    assert result["net_cost_cash"] == "6.0000"
    assert result["net_cash"] == "54.0000"
    assert data == before
    for field in ("broker_costs_verified", "profitable_edge_verified",
                  "may_execute_demo_order", "may_execute_real_order"):
        assert result[field] is False


def test_adverse_spread_stress_is_exact_and_monotone():
    data = _fixture()
    baseline = _audit(data)
    stressed = copy.deepcopy(data)
    for row in stressed[3]:
        row["spread_cash"] = "0.6000"
    report = _audit(stressed)
    assert Decimal(report["spread_cash"]) - Decimal(baseline["spread_cash"]) == Decimal("15.0000")
    assert Decimal(baseline["net_cash"]) - Decimal(report["net_cash"]) == Decimal("15.0000")
    assert report["net_cash"] == "39.0000"
    assert report["broker_costs_verified"] is False


def test_signed_financing_credit_reduces_net_cost_not_spread():
    data = _fixture()
    for row in data[3]:
        row["financing_cash"] = "-0.1000"
    result = _audit(data)
    assert result["financing_cash"] == "-3.0000"
    assert result["financing_debit_cash"] == "0.0000"
    assert result["financing_credit_cash"] == "3.0000"
    assert result["nonfinancing_charges_cash"] == "6.0000"
    assert result["net_cost_cash"] == "3.0000"
    assert result["net_cash"] == "57.0000"


@pytest.mark.parametrize("count", [1, 29])
def test_insufficient_holdout_does_not_expose_any_cost_totals(count):
    data = _fixture(count)
    result = _audit(data)
    assert result["status"] == "WITHHELD_INSUFFICIENT_HOLDOUT"
    assert result["outcome_metrics_withheld"] is True
    assert result["outcome_receipts_sha256"] is None
    for field in ("gross_cash", "spread_cash", "slippage_cash", "commission_cash",
                  "financing_cash", "fx_cash", "financing_debit_cash",
                  "financing_credit_cash", "nonfinancing_charges_cash",
                  "net_cost_cash", "net_cash"):
        assert result[field] is None
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False


def test_outcome_order_does_not_change_aggregate_or_receipt_digest():
    data = _fixture()
    baseline = _audit(data)
    shuffled = copy.deepcopy(data)
    shuffled[3].reverse()
    assert _audit(shuffled) == baseline


@pytest.mark.parametrize("mutation", [
    lambda d: d[3].pop(),
    lambda d: d[3][0].update(spread_cash="-0.0001"),
    lambda d: d[3][0].update(source_sha256="f" * 64),
    lambda d: d[3][0].update(observed_at_utc=d[3][0]["label_available_at_utc"] - 1),
    lambda d: d[3][0].update(receipt_sha256=d[3][1]["receipt_sha256"]),
])
def test_invalid_receipts_or_costs_fail_before_attribution(mutation):
    data = _fixture()
    mutation(data)
    with pytest.raises(ValueError):
        _audit(data)


def test_declared_source_cannot_be_relabelled_by_reanchoring():
    data = _fixture()
    data[0]["source"]["archive_sha256"] = "e" * 64
    data[2]["manifest_sha256"] = prepare_declared_holdout_manifest_sha256(data[0])
    with pytest.raises(ValueError, match="cross-source"):
        _audit(data)
