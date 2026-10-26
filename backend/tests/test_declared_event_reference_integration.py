"""Synthetic end-to-end CFD ledger-event references (not broker-authenticated)."""
import copy

import pytest

from app import declared_event_reference_audit as mod
from test_declared_split_component_anchor_audit import setup as component_setup


def setup():
    d = component_setup()
    d["event_reference_policy"] = {
        "reference_statement_sha256": d["component_policy"]["reference_statement_sha256"],
        "reference_captured_at": d["component_policy"]["reference_captured_at"],
        "reporting_currency": d["component_policy"]["reporting_currency"],
        "reporting_minor_units": d["component_policy"]["reporting_minor_units"],
        "expected_events": copy.deepcopy(d["ledger_events"]),
    }
    d["expected_event_reference_policy_sha256"] = mod.fingerprint_event_reference_policy(
        d["manifest"], d["ledger_policy"], d["expected_component_policy_sha256"],
        d["cutoff"], d["event_reference_policy"])
    return d


def test_complete_synthetic_end_to_end_receipts():
    result = mod.audit_declared_event_references(**setup())
    assert result["status"] == "COMPLETE_SELF_DECLARED_EVENTS_ONLY"
    assert result["reconciled_reporting_cash"] == "25.90"
    assert result["expected_events"] == 9
    assert result["may_execute_order"] is False
    assert result["broker_settlement_verified"] is False


def test_same_kind_offsetting_commission_errors_are_withheld():
    d = setup()
    d["ledger_events"][1]["amount_cash"] = "-0.50"
    d["ledger_events"][2]["amount_cash"] = "-0.50"
    result = mod.audit_declared_event_references(**d)
    assert result["status"] == "MISMATCH_DECLARED_EVENT_REFERENCES"
    assert result["reconciled_reporting_cash"] is None
    assert [(r["event_id"], r["fields"]) for r in result["event_mismatches"]] == [
        ("event-1", ["amount_cash"]), ("event-2", ["amount_cash"])]


def test_incomplete_financing_upstream_withholds():
    d = setup()
    d["financing_versions"].pop()
    result = mod.audit_declared_event_references(**d)
    assert result["status"].startswith("WITHHELD_UPSTREAM_")
    assert result["reconciled_reporting_cash"] is None


def test_reference_statement_identity_mismatch_rejected():
    d = setup()
    d["event_reference_policy"]["reference_statement_sha256"] = "f" * 64
    d["expected_event_reference_policy_sha256"] = mod.fingerprint_event_reference_policy(
        d["manifest"], d["ledger_policy"], d["expected_component_policy_sha256"],
        d["cutoff"], d["event_reference_policy"])
    with pytest.raises(ValueError, match="policies disagree"):
        mod.audit_declared_event_references(**d)


def test_frozen_reference_cannot_predate_declared_receipt():
    d = setup()
    latest = max(r["received_at"] for r in d["ledger_events"])
    d["event_reference_policy"]["reference_captured_at"] = latest - 1
    with pytest.raises(ValueError, match="not available"):
        mod.audit_declared_event_references(**d)
