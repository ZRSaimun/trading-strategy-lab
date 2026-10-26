"""Synthetic bracket-exit risk checks; no broker calls or data writes."""
from copy import deepcopy
import pytest
from app.paper_bracket_exit_guard import review_paper_exit_bracket

NOW = 1_790_000_000_000
POSITION = {
    "account": "demo-account", "provider": "test-provider", "venue": "test-venue",
    "instrument": "XAUUSD", "position_id": "position-001", "side": "LONG",
    "open_quantity": "2", "entry_price": "100", "stop_price": "99",
    "stressed_exit_price": "98", "point_value_cash": "10",
    "exit_cost_cash": "1", "max_position_loss_cash": "50",
    "snapshot_at_ms": NOW - 200, "complete_order_inventory": True,
    "inventory_revision": 1,
}
STOP = {
    "order_id": "stop-001", "position_id": "position-001",
    "account": "demo-account", "provider": "test-provider", "venue": "test-venue",
    "instrument": "XAUUSD", "role": "STOP", "side": "SELL",
    "status": "ACKNOWLEDGED", "quantity": "2", "filled_quantity": "0",
    "trigger_price": "99", "reduce_only": True, "oco_group": "bracket-001",
    "ack_at_ms": NOW - 300,
}
TARGET = {**STOP, "order_id": "target-001", "role": "TARGET", "trigger_price": "102"}


def run(patch=None, order_patch=None, extra=None):
    p, stop = deepcopy(POSITION), deepcopy(STOP)
    p.update(patch or {})
    stop.update(order_patch or {})
    return review_paper_exit_bracket(p, [stop, deepcopy(TARGET)] + (extra or []),
                                     server_now_ms=NOW)


def test_declared_coverage_is_never_execution_permission():
    result = run()
    assert result["declared_bracket_consistent"]
    assert result["declared_stressed_loss_cash"] == "41"
    assert result["status"] == "HOLD_RECONCILIATION"
    assert not result["may_execute_real_order"] and not result["may_execute_paper_order"]
    assert not result["broker_acknowledgements_verified"]


def test_deterministic_review_fingerprint():
    assert run()["review_sha256"] == run()["review_sha256"]
    assert run(order_patch={"quantity": "1"})["review_sha256"] != run()["review_sha256"]


@pytest.mark.parametrize("patch,reason", [
    ({"snapshot_at_ms": NOW - 3001}, "STALE_OR_FUTURE_INVENTORY"),
    ({"snapshot_at_ms": NOW + 1}, "STALE_OR_FUTURE_INVENTORY"),
    ({"complete_order_inventory": False}, "INCOMPLETE_ORDER_INVENTORY"),
    ({"max_position_loss_cash": "40"}, "STRESSED_LOSS_EXCEEDS_CAP"),
    ({"open_quantity": "3"}, "STOP_COVERAGE_NOT_EXACT"),
])
def test_position_fail_closed(patch, reason):
    result = run(patch=patch)
    assert reason in result["reasons"] and not result["declared_bracket_consistent"]


@pytest.mark.parametrize("patch,reason", [
    ({"status": "CANCEL_PENDING"}, "UNRESOLVED_ORDER_TRANSITION"),
    ({"status": "REPLACE_PENDING"}, "UNRESOLVED_ORDER_TRANSITION"),
    ({"status": "SUBMITTED"}, "UNRESOLVED_ORDER_TRANSITION"),
    ({"status": "CANCELED"}, "MISSING_OR_MULTIPLE_ACTIVE_STOPS"),
    ({"status": "PARTIALLY_FILLED", "filled_quantity": "1"}, "UNRECONCILED_EXIT_FILLS"),
    ({"filled_quantity": "1"}, "UNRECONCILED_EXIT_FILLS"),
    ({"reduce_only": False}, "REDUCE_ONLY_UNVERIFIED"),
    ({"quantity": "3"}, "STOP_COVERAGE_NOT_EXACT"),
    ({"trigger_price": "98.5"}, "STOP_TRIGGER_MISMATCH"),
    ({"oco_group": "other-bracket"}, "OCO_GROUP_MISMATCH"),
    ({"ack_at_ms": NOW + 1}, "ACK_AFTER_INVENTORY_SNAPSHOT"),
    ({"ack_at_ms": 0}, "MISSING_ORDER_ACK"),
])
def test_exit_transition_quarantined(patch, reason):
    result = run(order_patch=patch)
    assert reason in result["reasons"]
    assert not result["may_execute_real_order"]


def test_multiple_active_stops_quarantined():
    duplicate_stop = {**STOP, "order_id": "stop-002"}
    assert "MISSING_OR_MULTIPLE_ACTIVE_STOPS" in run(extra=[duplicate_stop])["reasons"]


def test_multiple_targets_quarantined():
    target2 = {**TARGET, "order_id": "target-002"}
    assert "MULTIPLE_ACTIVE_TARGETS" in run(extra=[target2])["reasons"]


def test_target_overcoverage_quarantined():
    target2 = {**TARGET, "quantity": "3"}
    result = review_paper_exit_bracket(POSITION, [STOP, target2], server_now_ms=NOW)
    assert "TARGET_OVER_COVERAGE" in result["reasons"]


def test_short_bracket_side_and_loss():
    p = {**POSITION, "side": "SHORT", "stop_price": "101",
         "stressed_exit_price": "102"}
    s = {**STOP, "side": "BUY", "trigger_price": "101"}
    t = {**TARGET, "side": "BUY", "trigger_price": "98"}
    result = review_paper_exit_bracket(p, [s, t], server_now_ms=NOW)
    assert result["declared_bracket_consistent"]
    assert result["declared_stressed_loss_cash"] == "41"


@pytest.mark.parametrize("patch", [
    {"open_quantity": 2}, {"open_quantity": "NaN"},
    {"inventory_revision": True}, {"complete_order_inventory": 1},
    {"entry_price": "1e2"}, {"side": "BUY"}, {"extra": "not-allowed"},
    {"stressed_exit_price": "100"}, {"max_position_loss_cash": "0"},
])
def test_malformed_position_rejected(patch):
    with pytest.raises(ValueError):
        run(patch=patch)


@pytest.mark.parametrize("patch", [
    {"account": "other-account"}, {"provider": "other-provider"},
    {"position_id": "other-position"}, {"side": "BUY"},
    {"quantity": "0"}, {"filled_quantity": "3"}, {"status": "UNKNOWN"},
    {"reduce_only": "true"}, {"role": "ENTRY"}, {"trigger_price": "Infinity"},
    {"extra": "not-allowed"}, {"order_id": "target-001"},
])
def test_malformed_exit_order_rejected(patch):
    with pytest.raises(ValueError):
        run(order_patch=patch)


def test_invalid_order_population_rejected():
    with pytest.raises(ValueError):
        review_paper_exit_bracket(POSITION, [STOP] * 101, server_now_ms=NOW)
    with pytest.raises(ValueError):
        review_paper_exit_bracket(POSITION, "not-an-order-list", server_now_ms=NOW)


def test_future_ack_cannot_be_used_to_certify_coverage():
    result = run(order_patch={"ack_at_ms": NOW + 100})
    assert "ACK_AFTER_INVENTORY_SNAPSHOT" in result["reasons"]


def test_target_wrong_side_is_quarantined():
    bad_target = {**TARGET, "trigger_price": "98"}
    result = review_paper_exit_bracket(POSITION, [STOP, bad_target], server_now_ms=NOW)
    assert "TARGET_NOT_PROFIT_SIDE" in result["reasons"]
