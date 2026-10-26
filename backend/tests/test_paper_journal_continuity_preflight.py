"""Synthetic, read-only journal-history continuity regressions.

Not a PostgreSQL concurrency test, broker acknowledgement, or live-order gate.
"""
import copy
import json

import pytest

from app.paper_journal_continuity_preflight import review_paper_journal_continuity

IDENTITY = {
    "instrument": "XAUUSD-DEMO", "provider": "SYNTHETIC", "venue": "TEST",
    "priceSide": "bid-ask", "pointValue": 1,
}


def snapshot(*, actions=None, orders=None, events=None, identity=None, version=1):
    return {
        "version": version,
        "identity": IDENTITY if identity is None else identity,
        "actions": ([{"kind": "SUBMIT", "request": {"clientOrderId": "order-1"}}]
                    if actions is None else actions),
        "orders": ([{"clientOrderId": "order-1", "status": "PENDING"}]
                   if orders is None else orders),
        "events": [] if events is None else events,
    }


def updated(previous=None):
    after = copy.deepcopy(snapshot() if previous is None else previous)
    after["actions"].append({"kind": "QUOTE", "quote": {"bid": 4000, "ask": 4001}})
    after["orders"][0]["status"] = "OPEN"
    after["events"].append({"orderId": "order-1", "status": "OPEN", "at": 100})
    return after


def review(before, after, previous_revision=0, next_revision=1):
    return review_paper_journal_continuity(
        json.dumps(before), json.dumps(after),
        expected_revision=previous_revision, next_revision=next_revision,
    )


def test_normal_append_preserves_history_but_never_authorizes_order():
    result = review(snapshot(), updated())
    assert result["assumption_checks_pass"] is True
    assert result["failed_checks"] == []
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["source_authenticated"] is False
    assert result["replay_verified"] is False
    assert result["journal_transaction_verified"] is False
    assert result["may_execute_paper_order"] is False
    assert result["may_execute_real_order"] is False


def test_snapshot_formatting_and_key_order_do_not_change_fingerprint():
    before, after = snapshot(), updated()
    original = review(before, after)
    alternative = review_paper_journal_continuity(
        json.dumps(before, indent=2, sort_keys=True),
        json.dumps(after, sort_keys=True),
        expected_revision=0, next_revision=1,
    )
    assert original["review_sha256"] == alternative["review_sha256"]


@pytest.mark.parametrize("mutation,failed_check", [
    ("drop_actions", "actions_append_only"),
    ("rewrite_actions", "actions_append_only"),
    ("drop_events", "events_append_only"),
    ("rewrite_events", "events_append_only"),
    ("drop_orders", "order_ids_retained_in_order"),
    ("reorder_orders", "order_ids_retained_in_order"),
    ("duplicate_orders", "order_ids_valid_and_unique"),
    ("bad_order_id", "order_ids_valid_and_unique"),
    ("no_new_action", "actions_advanced"),
    ("change_identity", "source_identity_unchanged"),
])
def test_history_tampering_fails_closed(mutation, failed_check):
    before = snapshot()
    if mutation in ("drop_events", "rewrite_events"):
        before["events"] = [{"orderId": "order-1", "status": "PENDING", "at": 1}]
    if mutation == "reorder_orders":
        before["orders"].append({"clientOrderId": "order-2", "status": "CLOSED"})
    after = updated(before)
    if mutation == "drop_actions":
        after["actions"] = []
    elif mutation == "rewrite_actions":
        after["actions"][0]["request"]["clientOrderId"] = "forged"
    elif mutation == "drop_events":
        after["events"] = []
    elif mutation == "rewrite_events":
        after["events"][0]["at"] = 999
    elif mutation == "drop_orders":
        after["orders"] = []
    elif mutation == "reorder_orders":
        after["orders"].reverse()
    elif mutation == "duplicate_orders":
        after["orders"].append(copy.deepcopy(after["orders"][0]))
    elif mutation == "bad_order_id":
        after["orders"][0]["clientOrderId"] = "../../secret"
    elif mutation == "no_new_action":
        after["actions"] = copy.deepcopy(before["actions"])
    elif mutation == "change_identity":
        after["identity"]["venue"] = "OTHER"
    result = review(before, after)
    assert result["assumption_checks_pass"] is False
    assert failed_check in result["failed_checks"]
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["may_execute_paper_order"] is False


@pytest.mark.parametrize("old_rev,new_rev", [
    (0, 0), (0, 2), (5, 4), (True, 1), (-1, 0), (0, False),
    (2**53 - 1, 2**53), (0, 2**53),
])
def test_invalid_or_noncontiguous_revisions(old_rev, new_rev):
    if type(old_rev) is not int or type(new_rev) is not int or old_rev < 0 or new_rev < 0 or old_rev >= 2**53 or new_rev >= 2**53:
        with pytest.raises(ValueError, match="revision"):
            review(snapshot(), updated(), old_rev, new_rev)
    else:
        result = review(snapshot(), updated(), old_rev, new_rev)
        assert "revision_contiguous" in result["failed_checks"]
        assert result["may_execute_real_order"] is False


@pytest.mark.parametrize("malformed", [
    '{"version":1,"version":1}',
    '{"version":true,"identity":{},"actions":[],"orders":[],"events":[]}',
    '{"version":1,"identity":{},"actions":[],"orders":[],"events":[]}',
    'not-json',
    '{"version":1,"identity":{},"actions":[1e999],"orders":[],"events":[]}',
])
def test_invalid_json_and_schema_are_rejected(malformed):
    with pytest.raises(ValueError, match="checkpoint"):
        review_paper_journal_continuity(
            json.dumps(snapshot()), malformed, expected_revision=0, next_revision=1,
        )


def test_oversized_checkpoint_is_rejected_before_parsing():
    with pytest.raises(ValueError, match="checkpoint"):
        review_paper_journal_continuity(
            json.dumps(snapshot()), " " * 8_000_001,
            expected_revision=0, next_revision=1,
        )


def test_no_previous_checkpoint_cannot_be_assumed_from_null():
    with pytest.raises(ValueError, match="checkpoint"):
        review_paper_journal_continuity(
            None, json.dumps(updated()), expected_revision=0, next_revision=1,
        )


def test_previous_malformed_order_ids_fail_closed():
    before = snapshot(orders=[{"status": "OPEN"}])
    result = review(before, updated())
    assert "order_ids_valid_and_unique" in result["failed_checks"]
    assert "order_ids_retained_in_order" in result["failed_checks"]
