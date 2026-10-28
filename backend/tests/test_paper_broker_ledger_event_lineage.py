"""Synthetic-only ledger event lineage checks. No DB, network or orders."""
from copy import deepcopy

import pytest

from app.paper_broker_ledger_event_lineage import (
    _event_digest,
    inspect_declared_ledger_event_lineage,
    inspect_declared_ledger_event_inventory_bridge,
)

NOW = 1_800_000_000_000
BROKER = "T212-INVEST-DEMO"
ACCOUNT = "demo-account"
INTENT = "a" * 64
RECEIPT = "b" * 64
ZERO = "0" * 64


def event(seq, name, evidence, stamp, previous, *, order="client1",
          broker=BROKER, account=ACCOUNT):
    return {"seq": seq, "broker": broker, "account": account,
            "order_id": order, "event": name, "evidence_sha": evidence,
            "recorded_at_ms": stamp, "prev_hash": previous,
            "event_hash": _event_digest(seq, broker, account, order, name,
                                        evidence, stamp, previous)}


def fixture():
    e1 = event(1, "PREPARED", INTENT, NOW - 5100, ZERO)
    e2 = event(2, "ATTEMPT_UNKNOWN", INTENT, NOW - 5001, e1["event_hash"])
    expected = {"broker": BROKER, "account_alias": ACCOUNT,
                "unresolved_orders": [{"client_order_id": "client1",
                                       "intent_sha": INTENT,
                                       "attempted_at_ms": NOW - 5000}]}
    summary = {"schema": "paper-submission-attempt-ledger-v1", "event_count": 2,
               "order_count": 1, "audit_tip_sha256": e2["event_hash"],
               "last_recorded_at_ms": NOW - 5001,
               "orders": [{"broker": BROKER, "account_alias": ACCOUNT,
                           "client_order_id": "client1", "status": "ATTEMPT_UNKNOWN"}]}
    return [expected, summary, [e1, e2], e2["event_hash"]]


def inspect(args):
    return inspect_declared_ledger_event_lineage(*args)


def test_matching_declared_lineage_never_authenticates_or_executes():
    result = inspect(fixture())
    assert result["status"] == "DECLARED_EVENT_LINEAGE_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["event_count"] == 2
    for flag in ("ledger_authenticated", "ledger_tip_custody_authenticated",
                 "broker_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


def test_intent_substitution_holds_even_if_context_digest_was_recomputed():
    args = fixture()
    args[0]["unresolved_orders"][0]["intent_sha"] = "c" * 64
    assert inspect(args)["failed_checks"] == ["ledger_event_intent_mismatch"]


def test_attempt_before_unknown_holds():
    args = fixture()
    args[0]["unresolved_orders"][0]["attempted_at_ms"] -= 2
    assert inspect(args)["failed_checks"] == ["ledger_unknown_attempt_time_mismatch"]


def test_stale_unknown_attempt_gap_holds():
    args = fixture()
    args[0]["unresolved_orders"][0]["attempted_at_ms"] += 60_001
    assert inspect(args)["failed_checks"] == ["ledger_unknown_attempt_time_mismatch"]


def test_maximum_allowed_unknown_attempt_gap():
    args = fixture()
    args[0]["unresolved_orders"][0]["attempted_at_ms"] = NOW - 5001 + 60_000
    assert inspect(args)["failed_checks"] == []


def test_pinned_tip_mismatch_holds():
    args = fixture()
    args[3] = "c" * 64
    assert inspect(args)["failed_checks"] == ["ledger_event_tip_mismatch"]


def test_declared_summary_tip_mismatch_holds():
    args = fixture()
    args[1]["audit_tip_sha256"] = "c" * 64
    assert inspect(args)["failed_checks"] == ["ledger_event_tip_mismatch"]


def test_last_time_mismatch_holds():
    args = fixture()
    args[1]["last_recorded_at_ms"] += 1
    assert inspect(args)["failed_checks"] == ["ledger_event_last_time_mismatch"]


def test_projection_status_mismatch_holds():
    args = fixture()
    args[1]["orders"][0]["status"] = "RECONCILED_FILLED"
    assert inspect(args)["failed_checks"] == ["ledger_event_projection_mismatch"]


def test_missing_unknown_population_holds():
    args = fixture()
    args[0]["unresolved_orders"][0]["client_order_id"] = "client2"
    assert inspect(args)["failed_checks"] == ["ledger_event_unknown_population_mismatch"]


@pytest.mark.parametrize("field,value", [
    ("seq", 3), ("prev_hash", "c" * 64), ("event_hash", "c" * 64),
    ("recorded_at_ms", NOW - 5200), ("event", "RECONCILED_FILLED"),
    ("evidence_sha", "d" * 64),
])
def test_replay_tamper_and_invalid_transition_fail_closed(field, value):
    args = fixture()
    args[2][1][field] = value
    with pytest.raises(ValueError):
        inspect(args)


@pytest.mark.parametrize("bad", [None, True, [], {}, [1], [None] * 10_001])
def test_invalid_event_population_rejected(bad):
    args = fixture()
    args[2] = bad
    with pytest.raises(ValueError):
        inspect(args)


def test_extra_field_rejected():
    args = fixture()
    args[2][0]["secret"] = "x"
    with pytest.raises(ValueError, match="schema"):
        inspect(args)


def test_event_count_missing_row_rejected():
    args = fixture()
    args[2].pop()
    with pytest.raises(ValueError, match="count"):
        inspect(args)


def test_repeated_unknown_for_same_account_rejected_even_with_valid_hashes():
    args = fixture()
    third = event(3, "PREPARED", "d" * 64, NOW - 5000, args[3], order="client2")
    args[2].append(third)
    args[1]["event_count"] = 3
    with pytest.raises(ValueError, match="unresolved account"):
        inspect(args)


def test_terminal_reconciliation_then_new_unknown_is_not_current_unknown():
    args = fixture()
    third = event(3, "RECONCILED_FILLED", RECEIPT, NOW - 4999, args[3])
    args[2].append(third)
    args[1].update(event_count=3, audit_tip_sha256=third["event_hash"],
                   last_recorded_at_ms=NOW - 4999)
    args[1]["orders"][0]["status"] = "RECONCILED_FILLED"
    args[3] = third["event_hash"]
    assert inspect(args)["failed_checks"] == ["ledger_event_unknown_population_mismatch"]


def test_terminal_receipt_reused_as_new_intent_rejected():
    args = fixture()
    third = event(3, "RECONCILED_FILLED", RECEIPT, NOW - 4999, args[3])
    fourth = event(4, "PREPARED", RECEIPT, NOW - 4998, third["event_hash"], order="client2")
    args[2] += [third, fourth]
    args[1]["event_count"] = 4
    with pytest.raises(ValueError, match="Reused intent"):
        inspect(args)


def test_input_immutability():
    args = fixture()
    before = deepcopy(args)
    inspect(args)
    assert args == before


def test_integration_keeps_all_permissions_disabled():
    from test_paper_broker_ledger_inventory_bridge import evidence
    args = evidence()
    expected, summary, events, tip = fixture()
    assert expected["unresolved_orders"][0]["intent_sha"] == args[0]["unresolved_orders"][0]["intent_sha"]
    args[6]["audit_tip_sha256"] = tip
    args[6]["last_recorded_at_ms"] = NOW - 5001
    args[7] = tip
    result = inspect_declared_ledger_event_inventory_bridge(*args, events)
    assert result["failed_checks"] == []
    assert result["declared_ledger_intent_lineage_matches"] is True
    assert result["ledger_intent_fingerprints_bound"] is False
    assert result["may_clear_unknown"] is False
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False


def test_integration_context_change_cannot_be_cleared_by_event_tip():
    from test_paper_broker_ledger_inventory_bridge import evidence
    args = evidence()
    _, _, events, tip = fixture()
    args[6]["audit_tip_sha256"] = tip
    args[6]["last_recorded_at_ms"] = NOW - 5001
    args[7] = tip
    args[0]["unresolved_orders"][0]["intent_sha"] = "c" * 64
    result = inspect_declared_ledger_event_inventory_bridge(*args, events)
    assert "reconciliation_context_digest_mismatch" in result["failed_checks"]
    assert "ledger_event_intent_mismatch" in result["failed_checks"]
    assert result["status"] == "HOLD_RECONCILIATION"
