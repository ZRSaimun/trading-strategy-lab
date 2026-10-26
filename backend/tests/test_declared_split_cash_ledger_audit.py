"""Synthetic end-to-end split cash ledger census and fail-closed regressions."""
import copy
from decimal import Decimal

import pytest

from app import declared_split_cash_ledger_audit as mod
from test_declared_cash_posting_audit import setup as cash_setup


KINDS = ("PNL", "COMMISSION", "FINANCING", "FX_CONVERSION", "REVERSAL")


def setup():
    data = cash_setup()
    data.pop("posting_policy")
    data.pop("expected_posting_policy_sha256")
    data.pop("postings")
    values = [
        ("p1", "PNL", "20.00"), ("p1", "COMMISSION", "-0.60"),
        ("p1", "COMMISSION", "-0.40"), ("p1", "FINANCING", "-2.00"),
        ("p1", "FX_CONVERSION", "-0.08"),
        ("p2", "PNL", "10.00"), ("p2", "COMMISSION", "-0.50"),
        ("p2", "FINANCING", "-0.50"), ("p2", "FX_CONVERSION", "-0.02"),
    ]
    closes = {p["position_id"]: p["closed_at"] for p in data["manifest"]["positions"]}
    events = []
    for i, (pid, kind, cash) in enumerate(values):
        events.append({
            "event_id": "event-" + str(i), "position_id": pid,
            "provider": "Synthetic", "venue": "DEMO", "account_alias": "paper1",
            "currency": "USD", "kind": kind,
            "posted_at": closes[pid] + 1, "received_at": closes[pid] + 2,
            "amount_cash": cash, "statement_sha256": "d" * 64,
        })
    census = [
        {"position_id": pid, "kind": kind,
         "count": sum(1 for r in events if r["position_id"] == pid and r["kind"] == kind)}
        for pid in ("p1", "p2") for kind in KINDS
    ]
    policy = {
        "max_posting_delay_seconds": 10,
        "max_receipt_lag_seconds": 10,
        "expected_receipts": census,
    }
    data["ledger_policy"] = policy
    data["expected_ledger_policy_sha256"] = mod.fingerprint_split_ledger_policy(
        data["manifest"], data["fx_policy"], data["expected_fx_policy_sha256"],
        data["expected_rounding_policy_sha256"], data["cutoff"], policy,
    )
    data["ledger_events"] = events
    return data


def run(data=None):
    return mod.audit_declared_split_cash_ledger(**(setup() if data is None else data))


def test_end_to_end_split_financing_fills_fx_rounding_to_cash():
    result = run()
    assert result["status"] == "COMPLETE_SELF_DECLARED_ONLY"
    assert result["reconciled_reporting_cash"] == "25.90"
    assert result["expected_positions"] == 2
    assert result["expected_events"] == 9
    assert result["mismatches"] == []
    for key in ("source_authenticated", "broker_settlement_verified",
                "untouched_holdout_verified", "verified_profitability", "may_execute_order"):
        assert result[key] is False


def test_split_commissions_reconcile_without_net_close_receipt():
    data = setup()
    assert [r["amount_cash"] for r in data["ledger_events"] if r["kind"] == "COMMISSION" and r["position_id"] == "p1"] == ["-0.60", "-0.40"]
    assert run(data)["status"] == "COMPLETE_SELF_DECLARED_ONLY"


def test_missing_financing_entry_withholds_all_cash():
    data = setup()
    data["ledger_events"].pop(3)
    result = run(data)
    assert result["status"] == "WITHHELD_INCOMPLETE_DECLARED_LEDGER"
    assert result["reconciled_reporting_cash"] is None
    assert result["missing"] == [{"position_id": "p1", "kind": "FINANCING", "missing": 1}]


def test_empty_population_withholds():
    data = setup()
    data["ledger_events"] = []
    result = run(data)
    assert result["status"] == "WITHHELD_INCOMPLETE_DECLARED_LEDGER"
    assert result["observed_events"] == 0
    assert result["reconciled_reporting_cash"] is None


def test_wrong_cash_withholds_aggregate_and_reports_exact_delta():
    data = setup()
    data["ledger_events"][1]["amount_cash"] = "-0.61"
    result = run(data)
    assert result["status"] == "MISMATCH_DECLARED_LEDGER"
    assert result["reconciled_reporting_cash"] is None
    assert result["mismatches"] == [{
        "position_id": "p1", "hypothetical_rounded_cash": "16.92",
        "declared_ledger_cash": "16.91", "difference_cash": "-0.01",
    }]


def test_balanced_component_tampering_cannot_be_authenticated():
    data = setup()
    data["ledger_events"][0]["amount_cash"] = "21.00"
    data["ledger_events"][3]["amount_cash"] = "-3.00"
    result = run(data)
    assert result["status"] == "COMPLETE_SELF_DECLARED_ONLY"
    assert result["broker_settlement_verified"] is False
    assert result["source_authenticated"] is False
    assert result["ledger_declaration_sha256"] != run()["ledger_declaration_sha256"]


def test_reordering_events_and_census_is_deterministic_and_does_not_mutate():
    data = setup()
    original = copy.deepcopy(data)
    baseline = run(data)
    data["ledger_events"].reverse()
    data["ledger_policy"]["expected_receipts"].reverse()
    assert run(data) == baseline
    assert original["ledger_events"] == list(reversed(data["ledger_events"]))


def test_missing_financing_upstream_withholds():
    data = setup()
    data["financing_versions"].pop()
    result = run(data)
    assert result["status"] == "WITHHELD_INCOMPLETE_UPSTREAM"
    assert result["reconciled_reporting_cash"] is None


def test_financing_revision_recomputes_net_and_detects_mismatch():
    data = setup()
    data["financing_versions"].append(dict(
        data["financing_versions"][0], receipt_id="revised-later",
        revision=2, amount_currency="2.00", published_at=490, ingested_at=495,
    ))
    result = run(data)
    assert result["status"] == "MISMATCH_DECLARED_LEDGER"
    assert result["reconciled_reporting_cash"] is None


@pytest.mark.parametrize("field,value", [
    ("provider", "Other"), ("venue", "LIVE"), ("account_alias", "other"),
    ("position_id", ["p1"]), ("kind", {"unexpected": "dict"}),
    ("currency", "GBP"), ("kind", "OTHER"), ("event_id", ""),
    ("statement_sha256", "bad"), ("posted_at", 399), ("posted_at", 412),
    ("received_at", 400), ("received_at", 420), ("received_at", 501),
    ("posted_at", True), ("received_at", 500.0),
    ("amount_cash", "NaN"), ("amount_cash", "1e2"),
    ("amount_cash", "20.000"), ("amount_cash", "-0.00"),
    ("amount_cash", "1" * 81), ("extra", "bad"),
])
def test_invalid_events_rejected(field, value):
    data = setup()
    data["ledger_events"][0][field] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("mutate", [
    lambda p: p.append(copy.deepcopy(p[0])),
    lambda p: p.__setitem__(1, dict(p[1], event_id="event-0")),
    lambda p: p.__setitem__(1, dict(p[1], position_id="unknown")),
    lambda p: p.__setitem__(1, dict(p[1], kind="PNL")),
])
def test_duplicate_extra_or_unregistered_events_rejected(mutate):
    data = setup()
    mutate(data["ledger_events"])
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("field,value", [
    ("max_posting_delay_seconds", True),
    ("max_posting_delay_seconds", -1),
    ("max_posting_delay_seconds", 2592001),
    ("max_receipt_lag_seconds", 2.5),
    ("extra", 10),
])
def test_invalid_policy_rejected(field, value):
    data = setup()
    data["ledger_policy"][field] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("mutate", [
    lambda c: c.pop(),
    lambda c: c.append(copy.deepcopy(c[0])),
    lambda c: c.__setitem__(0, dict(c[0], kind="OTHER")),
    lambda c: c.__setitem__(0, dict(c[0], count=True)),
    lambda c: c.__setitem__(0, dict(c[0], count=-1)),
    lambda c: c.__setitem__(0, dict(c[0], count=33)),
    lambda c: c.__setitem__(0, dict(c[0], count=0)),
    lambda c: c.__setitem__(0, dict(c[0], position_id="unknown")),
    lambda c: c.__setitem__(0, dict(c[0], position_id=["p1"])),
])
def test_invalid_or_incomplete_kind_census_rejected(mutate):
    data = setup()
    mutate(data["ledger_policy"]["expected_receipts"])
    with pytest.raises(ValueError):
        run(data)


def test_changed_census_requires_new_policy_digest():
    data = setup()
    data["ledger_policy"]["expected_receipts"][1]["count"] += 1
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_changed_position_close_requires_new_policy_digest():
    data = setup()
    data["manifest"]["positions"][0]["closed_at"] = 401
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_changed_source_statement_changes_receipt_fingerprint_not_authenticity():
    data = setup()
    baseline = run()
    data["ledger_events"][0]["statement_sha256"] = "e" * 64
    result = run(data)
    assert result["ledger_declaration_sha256"] != baseline["ledger_declaration_sha256"]
    assert result["source_authenticated"] is False
    assert Decimal(result["reconciled_reporting_cash"]) == Decimal("25.90")


def test_pnl_receipt_must_post_at_or_after_close():
    data = setup()
    data["ledger_events"][0]["posted_at"] = 399
    data["ledger_events"][0]["received_at"] = 400
    with pytest.raises(ValueError, match="out-of-position"):
        run(data)


def test_financing_receipt_can_post_during_position():
    data = setup()
    row = data["ledger_events"][3]
    opened = next(p["opened_at"] for p in data["manifest"]["positions"] if p["position_id"] == "p1")
    row["posted_at"] = opened + 1
    row["received_at"] = opened + 2
    assert run(data)["status"] == "COMPLETE_SELF_DECLARED_ONLY"


def test_excess_event_population_rejected():
    data = setup()
    data["ledger_events"] *= 228
    with pytest.raises(ValueError, match="Unbounded"):
        run(data)


def test_unsupported_reporting_minor_units_rejected():
    data = setup()
    data["rounding_policy"]["reporting_minor_units"] = 9
    with pytest.raises(ValueError):
        run(data)
