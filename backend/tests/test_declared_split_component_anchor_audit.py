"""Synthetic cross-component anchors; no brokerage or real-market evidence."""
import copy
from decimal import Decimal

import pytest

from app import declared_split_component_anchor_audit as mod
from test_declared_split_cash_ledger_audit import setup as ledger_setup

KINDS = ("PNL", "COMMISSION", "FINANCING", "FX_CONVERSION", "REVERSAL")


def setup():
    data = ledger_setup()
    events = data["ledger_events"]
    anchors = []
    for pid in ("p1", "p2"):
        for kind in KINDS:
            amount = sum((Decimal(e["amount_cash"]) for e in events
                          if e["position_id"] == pid and e["kind"] == kind), Decimal(0))
            anchors.append({"position_id": pid, "kind": kind, "amount_cash": format(amount, "f")})
    data["component_policy"] = {
        "reporting_currency": "USD", "reporting_minor_units": 2,
        "reference_statement_sha256": "e" * 64,
        "reference_captured_at": data["cutoff"],
        "expected_components": anchors,
    }
    data["expected_component_policy_sha256"] = mod.fingerprint_split_component_policy(
        data["manifest"], data["ledger_policy"], data["expected_ledger_policy_sha256"],
        data["cutoff"], data["component_policy"],
    )
    return data


def run(data=None):
    return mod.audit_declared_split_component_anchors(**(setup() if data is None else data))


def test_complete_synthetic_component_reference_matches():
    result = run()
    assert result["status"] == "COMPLETE_SELF_DECLARED_COMPONENTS_ONLY"
    assert result["reconciled_reporting_cash"] == "25.90"
    assert result["expected_positions"] == 2
    assert result["expected_components"] == 10
    assert result["component_mismatches"] == []
    for key in ("source_authenticated", "broker_settlement_verified",
                "untouched_holdout_verified", "verified_profitability", "may_execute_order"):
        assert result[key] is False


def test_offsetting_pnl_financing_tampering_now_withholds():
    data = setup()
    data["ledger_events"][0]["amount_cash"] = "21.00"
    data["ledger_events"][3]["amount_cash"] = "-3.00"
    result = run(data)
    assert result["status"] == "MISMATCH_DECLARED_COMPONENTS"
    assert result["reconciled_reporting_cash"] is None
    assert [(r["position_id"], r["kind"], r["difference_cash"])
            for r in result["component_mismatches"]] == [
                ("p1", "FINANCING", "-1.00"), ("p1", "PNL", "1.00")]


def test_offsetting_within_same_kind_is_not_detected_by_category_totals():
    data = setup()
    data["ledger_events"][1]["amount_cash"] = "-0.50"
    data["ledger_events"][2]["amount_cash"] = "-0.50"
    result = run(data)
    assert result["status"] == "COMPLETE_SELF_DECLARED_COMPONENTS_ONLY"
    assert result["broker_settlement_verified"] is False
    assert result["ledger_declaration_sha256"] != run()["ledger_declaration_sha256"]


def test_missing_financing_event_withholds_before_component_comparison():
    data = setup()
    data["ledger_events"].pop(3)
    result = run(data)
    assert result["status"] == "WITHHELD_UPSTREAM_WITHHELD_INCOMPLETE_DECLARED_LEDGER"
    assert result["reconciled_reporting_cash"] is None


def test_upstream_net_mismatch_withholds():
    data = setup()
    data["ledger_events"][0]["amount_cash"] = "20.01"
    result = run(data)
    assert result["status"] == "WITHHELD_UPSTREAM_MISMATCH_DECLARED_LEDGER"
    assert result["reconciled_reporting_cash"] is None


def test_upstream_financing_gap_withholds():
    data = setup()
    data["financing_versions"].pop()
    result = run(data)
    assert result["status"] == "WITHHELD_UPSTREAM_WITHHELD_INCOMPLETE_UPSTREAM"
    assert result["reconciled_reporting_cash"] is None


def test_reordering_is_deterministic_and_does_not_mutate():
    data = setup()
    baseline = run(data)
    data["ledger_events"].reverse()
    data["component_policy"]["expected_components"].reverse()
    snapshot = copy.deepcopy(data)
    assert run(data) == baseline
    assert data == snapshot


def test_reference_amount_mutation_requires_new_digest():
    data = setup()
    data["component_policy"]["expected_components"][0]["amount_cash"] = "21.00"
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_new_reference_with_matching_net_but_wrong_components_withholds():
    data = setup()
    data["component_policy"]["expected_components"][0]["amount_cash"] = "21.00"
    data["component_policy"]["expected_components"][2]["amount_cash"] = "-3.00"
    data["expected_component_policy_sha256"] = mod.fingerprint_split_component_policy(
        data["manifest"], data["ledger_policy"], data["expected_ledger_policy_sha256"],
        data["cutoff"], data["component_policy"])
    assert run(data)["status"] == "MISMATCH_DECLARED_COMPONENTS"


@pytest.mark.parametrize("field,value", [
    ("reporting_currency", "GBP"), ("reporting_currency", "usd"),
    ("reporting_minor_units", 3), ("reporting_minor_units", True),
    ("reporting_minor_units", 7),
    ("reference_statement_sha256", "invalid"),
    ("reference_captured_at", True), ("reference_captured_at", 501),
    ("expected_components", []), ("unexpected", 1),
])
def test_invalid_component_policy_rejected(field, value):
    data = setup()
    data["component_policy"][field] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("value", ["NaN", "1e2", "-0.00", "1.000", "1" * 81, 1, None])
def test_invalid_anchor_cash_rejected(value):
    data = setup()
    data["component_policy"]["expected_components"][0]["amount_cash"] = value
    with pytest.raises(ValueError):
        run(data)


def test_duplicate_reference_kind_rejected():
    data = setup()
    data["component_policy"]["expected_components"][0] = copy.deepcopy(
        data["component_policy"]["expected_components"][1])
    with pytest.raises(ValueError, match="duplicate"):
        run(data)


def test_zero_receipt_kind_cannot_claim_nonzero_reference():
    data = setup()
    row = next(r for r in data["component_policy"]["expected_components"]
               if r["position_id"] == "p1" and r["kind"] == "REVERSAL")
    row["amount_cash"] = "1.00"
    with pytest.raises(ValueError, match="Nonzero reference"):
        run(data)


def test_census_digest_and_reference_identity_are_bound():
    data = setup()
    data["expected_ledger_policy_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_different_reference_statement_changes_fingerprint_not_authenticity():
    data = setup()
    original = data["expected_component_policy_sha256"]
    data["component_policy"]["reference_statement_sha256"] = "f" * 64
    new = mod.fingerprint_split_component_policy(
        data["manifest"], data["ledger_policy"], data["expected_ledger_policy_sha256"],
        data["cutoff"], data["component_policy"])
    assert new != original
    data["expected_component_policy_sha256"] = new
    assert run(data)["source_authenticated"] is False
