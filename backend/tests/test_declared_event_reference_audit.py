"""Synthetic per-event declared cash-reference checks; not broker evidence."""
import copy

import pytest

from app import declared_event_reference_audit as mod

KINDS = ("PNL", "COMMISSION", "FINANCING", "FX_CONVERSION", "REVERSAL")


def synthetic():
    events = []
    for eid, pid, kind, cash in [
        ("a", "p1", "PNL", "5.00"),
        ("b", "p1", "COMMISSION", "-1.00"),
        ("c", "p1", "COMMISSION", "-2.00"),
        ("d", "p2", "PNL", "3.00"),
    ]:
        events.append({"event_id": eid, "position_id": pid, "kind": kind,
                       "provider": "Synthetic", "venue": "DEMO", "account_alias": "paper1",
                       "currency": "USD", "posted_at": 100, "received_at": 101,
                       "amount_cash": cash, "statement_sha256": "d" * 64})
    manifest = {"source": {"provider": "Synthetic", "venue": "DEMO",
                           "account_alias": "paper1"},
                "positions": [{"position_id": "p1"}, {"position_id": "p2"}]}
    ledger_policy = {"expected_receipts": [
        {"position_id": pid, "kind": kind,
         "count": sum(e["position_id"] == pid and e["kind"] == kind for e in events)}
        for pid in ("p1", "p2") for kind in KINDS]}
    component_policy = {"reporting_currency": "USD", "reporting_minor_units": 2,
                        "reference_statement_sha256": "e" * 64,
                        "reference_captured_at": 110}
    policy = {**component_policy, "expected_events": copy.deepcopy(events)}
    return {"manifest": manifest, "ledger_policy": ledger_policy,
            "component_policy": component_policy, "event_reference_policy": policy,
            "ledger_events": events, "cutoff": 120,
            "expected_component_policy_sha256": "a" * 64}


def fingerprint(d):
    return mod.fingerprint_event_reference_policy(
        d["manifest"], d["ledger_policy"],
        d["expected_component_policy_sha256"], d["cutoff"],
        d["event_reference_policy"])


def run(monkeypatch, d, *, status="COMPLETE_SELF_DECLARED_COMPONENTS_ONLY"):
    def upstream(*args, **kwargs):
        return {"status": status,
                "component_policy_sha256": d["expected_component_policy_sha256"],
                "cutoff": d["cutoff"], "source_authenticated": False,
                "may_execute_order": False, "ledger_declaration_sha256": "f" * 64,
                "expected_positions": 2, "reconciled_reporting_cash": "5.00"}
    monkeypatch.setattr(mod, "audit_declared_split_component_anchors", upstream)
    return mod.audit_declared_event_references(
        d["manifest"], [], "a" * 64, [], "b" * 64, [],
        cutoff=d["cutoff"], fx_policy={}, expected_fx_policy_sha256="c" * 64,
        fx_quotes=[], rounding_policy={}, expected_rounding_policy_sha256="d" * 64,
        ledger_policy=d["ledger_policy"], expected_ledger_policy_sha256="e" * 64,
        ledger_events=d["ledger_events"], component_policy=d["component_policy"],
        expected_component_policy_sha256=d["expected_component_policy_sha256"],
        event_reference_policy=d["event_reference_policy"],
        expected_event_reference_policy_sha256=fingerprint(d))


def test_matching_declared_events_do_not_authenticate_broker(monkeypatch):
    d = synthetic()
    result = run(monkeypatch, d)
    assert result["status"] == "COMPLETE_SELF_DECLARED_EVENTS_ONLY"
    assert result["expected_events"] == 4
    assert result["reconciled_reporting_cash"] == "5.00"
    for key in ("source_authenticated", "broker_settlement_verified",
                "untouched_holdout_verified", "verified_profitability", "may_execute_order"):
        assert result[key] is False


def test_same_kind_offsetting_receipt_tamper_is_detected(monkeypatch):
    d = synthetic()
    d["ledger_events"][1]["amount_cash"] = "-0.50"
    d["ledger_events"][2]["amount_cash"] = "-2.50"
    result = run(monkeypatch, d)
    assert result["status"] == "MISMATCH_DECLARED_EVENT_REFERENCES"
    assert result["reconciled_reporting_cash"] is None
    assert result["event_mismatches"] == [
        {"event_id": "b", "fields": ["amount_cash"]},
        {"event_id": "c", "fields": ["amount_cash"]}]


@pytest.mark.parametrize("field,value", [
    ("amount_cash", "-0.99"), ("posted_at", 99), ("received_at", 102),
    ("statement_sha256", "f" * 64), ("kind", "FINANCING"),
    ("position_id", "p2"), ("currency", "GBP"),
    ("provider", "Other"), ("venue", "LIVE"),
    ("account_alias", "other"),
])
def test_event_field_mutation_detected(monkeypatch, field, value):
    d = synthetic()
    d["ledger_events"][0][field] = value
    result = run(monkeypatch, d)
    assert result["status"] == "MISMATCH_DECLARED_EVENT_REFERENCES"
    assert field in result["event_mismatches"][0]["fields"]


def test_relabelled_event_ids_detect_missing_and_extra(monkeypatch):
    d = synthetic()
    d["ledger_events"][0]["event_id"] = "new"
    result = run(monkeypatch, d)
    assert result["missing_event_ids"] == ["a"]
    assert result["extra_event_ids"] == ["new"]
    assert result["reconciled_reporting_cash"] is None


def test_missing_receipt_never_emits_net(monkeypatch):
    d = synthetic()
    d["ledger_events"].pop()
    result = run(monkeypatch, d)
    assert result["missing_event_ids"] == ["d"]
    assert result["reconciled_reporting_cash"] is None


def test_upstream_withheld_is_not_rescued_by_matching_references(monkeypatch):
    d = synthetic()
    result = run(monkeypatch, d, status="MISMATCH_DECLARED_COMPONENTS")
    assert result["status"] == "WITHHELD_UPSTREAM_MISMATCH_DECLARED_COMPONENTS"
    assert result["reconciled_reporting_cash"] is None


def test_reference_reordering_is_deterministic_and_nonmutating(monkeypatch):
    d = synthetic()
    baseline = run(monkeypatch, d)
    d["event_reference_policy"]["expected_events"].reverse()
    d["ledger_events"].reverse()
    snapshot = copy.deepcopy(d)
    assert run(monkeypatch, d) == baseline
    assert d == snapshot


@pytest.mark.parametrize("field,value", [
    ("reference_statement_sha256", "bad"), ("reference_captured_at", 121),
    ("reference_captured_at", 100), ("reference_captured_at", True),
    ("reporting_currency", "usd"), ("reporting_minor_units", 7),
    ("reporting_minor_units", True), ("unexpected", 1),
])
def test_invalid_reference_policy_rejected(field, value):
    d = synthetic()
    d["event_reference_policy"][field] = value
    with pytest.raises(ValueError):
        fingerprint(d)


@pytest.mark.parametrize("field,value", [
    ("amount_cash", "NaN"), ("amount_cash", "1e2"),
    ("amount_cash", "-0.00"), ("amount_cash", "1.001"),
    ("amount_cash", "1" * 81), ("amount_cash", 1),
    ("received_at", 111), ("posted_at", 102),
    ("posted_at", True), ("received_at", 101.0),
    ("statement_sha256", "bad"), ("provider", "Other"),
    ("event_id", ""), ("kind", "UNKNOWN"),
    ("position_id", "other"), ("currency", "GBP"),
    ("extra", 1),
])
def test_invalid_reference_row_rejected(field, value):
    d = synthetic()
    d["event_reference_policy"]["expected_events"][0][field] = value
    with pytest.raises(ValueError):
        fingerprint(d)


def test_missing_duplicate_or_relabelled_reference_rejected():
    for mutate in (
        lambda rows: rows.pop(),
        lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
        lambda rows: rows.__setitem__(1, dict(rows[1], kind="PNL")),
    ):
        d = synthetic()
        mutate(d["event_reference_policy"]["expected_events"])
        with pytest.raises(ValueError):
            fingerprint(d)


def test_reference_mutation_changes_fingerprint_and_requires_reapproval():
    d = synthetic()
    first = fingerprint(d)
    d["event_reference_policy"]["expected_events"][0]["amount_cash"] = "5.01"
    assert fingerprint(d) != first


def test_reference_component_policy_mismatch_rejected(monkeypatch):
    d = synthetic()
    d["component_policy"]["reference_captured_at"] = 109
    with pytest.raises(ValueError, match="policies disagree"):
        run(monkeypatch, d)


def test_reference_not_available_by_cutoff_is_rejected():
    d = synthetic()
    d["cutoff"] = 109
    with pytest.raises(ValueError):
        fingerprint(d)
