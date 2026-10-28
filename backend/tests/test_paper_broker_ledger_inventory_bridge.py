"""Synthetic-only tests for the read-only ledger/inventory bridge."""
from copy import deepcopy

import pytest

from app.paper_broker_ledger_inventory_bridge import (
    inspect_declared_ledger_inventory_bridge,
)
from test_paper_broker_reconciliation_context_anchor import anchored

TIP = "c" * 64


def evidence():
    args = list(anchored())
    expected, snapshots, clocks, *_ = args
    ledger = {
        "schema": "paper-submission-attempt-ledger-v1",
        "event_count": 2,
        "order_count": 1,
        "audit_tip_sha256": TIP,
        "last_recorded_at_ms": expected["unresolved_orders"][0]["attempted_at_ms"],
        "orders": [{
            "broker": expected["broker"],
            "account_alias": expected["account_alias"],
            "client_order_id": "client1",
            "status": "ATTEMPT_UNKNOWN",
        }],
        "status": "HOLD_RECONCILIATION",
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
        "warning": "Local evidence only, not broker proof.",
    }
    return args + [ledger, TIP]


def inspect(args):
    return inspect_declared_ledger_inventory_bridge(*args)


def test_matching_declared_evidence_never_authorizes_orders():
    result = inspect(evidence())
    assert result["status"] == "DECLARED_LEDGER_INVENTORY_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["expected_unknown_count"] == 1
    assert result["ledger_order_count"] == 1
    for name in ("ledger_authenticated", "ledger_tip_custody_authenticated",
                 "ledger_intent_fingerprints_bound", "broker_authenticated",
                 "may_clear_unknown", "may_submit_paper_order",
                 "may_submit_real_order"):
        assert result[name] is False


def test_missing_unknown_ledger_row_holds():
    args = evidence()
    args[6]["orders"][0]["status"] = "RECONCILED_FILLED"
    result = inspect(args)
    assert result["failed_checks"] == ["ledger_unknown_population_mismatch"]


def test_extra_unknown_in_same_account_holds():
    args = evidence()
    extra = deepcopy(args[6]["orders"][0])
    extra["client_order_id"] = "client2"
    args[6]["orders"].append(extra)
    args[6]["order_count"] = 2
    args[6]["event_count"] = 4
    assert "ledger_unknown_population_mismatch" in inspect(args)["failed_checks"]


def test_unknown_in_another_account_does_not_change_target_population():
    args = evidence()
    extra = deepcopy(args[6]["orders"][0])
    extra["account_alias"] = "other-account"
    args[6]["orders"].append(extra)
    args[6]["order_count"] = 2
    args[6]["event_count"] = 4
    assert inspect(args)["failed_checks"] == []


def test_changed_ledger_tip_holds_even_with_matching_inventory():
    args = evidence()
    args[6]["audit_tip_sha256"] = "d" * 64
    assert inspect(args)["failed_checks"] == ["ledger_audit_tip_mismatch"]


@pytest.mark.parametrize("bad", [None, True, 5, "0" * 64, "C" * 64, "c" * 63])
def test_invalid_pinned_tip_rejected(bad):
    args = evidence()
    args[7] = bad
    with pytest.raises(ValueError, match="prior ledger tip"):
        inspect(args)


@pytest.mark.parametrize("key", ["may_submit_real_order", "may_submit_paper_order"])
def test_unsafe_ledger_execution_claim_rejected(key):
    args = evidence()
    args[6][key] = True
    with pytest.raises(ValueError, match="unsafe execution claim"):
        inspect(args)


@pytest.mark.parametrize("key,value", [
    ("schema", "paper-submission-attempt-ledger-v2"),
    ("status", "CLEARED"),
    ("warning", ""),
])
def test_unsupported_summary_claims_rejected(key, value):
    args = evidence()
    args[6][key] = value
    with pytest.raises(ValueError):
        inspect(args)


def test_missing_summary_field_rejected():
    args = evidence()
    del args[6]["orders"]
    with pytest.raises(ValueError, match="schema"):
        inspect(args)


def test_extra_summary_field_rejected():
    args = evidence()
    args[6]["may_clear_unknown"] = True
    with pytest.raises(ValueError, match="schema"):
        inspect(args)


@pytest.mark.parametrize("bad", [None, True, -1, 0, 10001, "2"])
def test_invalid_event_count_rejected(bad):
    args = evidence()
    args[6]["event_count"] = bad
    with pytest.raises(ValueError, match="event count"):
        inspect(args)


def test_insufficient_event_count_holds():
    args = evidence()
    args[6]["event_count"] = 1
    assert inspect(args)["failed_checks"] == ["ledger_event_population_insufficient"]


def test_order_count_mismatch_rejected():
    args = evidence()
    args[6]["order_count"] = 2
    with pytest.raises(ValueError, match="counts"):
        inspect(args)


def test_duplicate_ledger_order_identity_rejected():
    args = evidence()
    args[6]["orders"].append(deepcopy(args[6]["orders"][0]))
    args[6]["order_count"] = 2
    args[6]["event_count"] = 4
    with pytest.raises(ValueError, match="Duplicate ledger order identity"):
        inspect(args)


def test_invalid_ledger_order_status_rejected():
    args = evidence()
    args[6]["orders"][0]["status"] = "SUBMITTED"
    with pytest.raises(ValueError, match="order state"):
        inspect(args)


def test_invalid_ledger_order_id_rejected():
    args = evidence()
    args[6]["orders"][0]["client_order_id"] = "bad order id"
    with pytest.raises(ValueError, match="client order ID"):
        inspect(args)


def test_invalid_ledger_last_time_rejected():
    args = evidence()
    args[6]["last_recorded_at_ms"] = True
    with pytest.raises(ValueError, match="last event time"):
        inspect(args)


def test_underlying_context_tamper_still_holds():
    args = evidence()
    args[0]["unresolved_orders"][0]["intent_sha"] = "b" * 64
    assert "reconciliation_context_digest_mismatch" in inspect(args)["failed_checks"]


def test_underlying_snapshot_tamper_still_holds():
    args = evidence()
    args[1][1]["pages"][0]["orders"][0]["fills"][0]["quantity"] = "0.5"
    result = inspect(args)
    assert "snapshot_digest_mismatch" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_no_input_mutation():
    args = evidence()
    before = deepcopy(args)
    inspect(args)
    assert args == before
