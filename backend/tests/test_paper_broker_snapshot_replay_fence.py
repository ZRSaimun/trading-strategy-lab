"""Synthetic, disconnected broker snapshot transition regression tests."""
from copy import deepcopy

import pytest

from app.paper_broker_snapshot_replay_fence import inspect_declared_snapshot_transition

NOW = 1_800_000_000_000


def sample():
    expected = {
        "broker": "T212-INVEST-DEMO", "account_alias": "demo-account",
        "max_snapshot_age_ms": 5000, "max_transport_lag_ms": 2000,
        "unresolved_orders": [{"client_order_id": "client1", "intent_sha": "a" * 64,
                               "instrument": "ABC", "side": "BUY", "quantity": "2",
                               "attempted_at_ms": NOW - 4000}],
    }
    previous = {
        "broker": "T212-INVEST-DEMO", "account_alias": "demo-account",
        "snapshot_id": "snapshot1", "sequence": 1,
        "observed_at_ms": NOW - 1400, "received_at_ms": NOW - 1100,
        "pages": [{"snapshot_id": "snapshot1", "index": 0, "total_pages": 1,
                   "complete": True,
                   "orders": [{"client_order_id": "client1", "broker_order_id": "broker1",
                               "instrument": "ABC", "side": "BUY", "quantity": "2",
                               "status": "PARTIAL", "filled_quantity": "1",
                               "fills": [{"fill_id": "fill1", "quantity": "1",
                                          "filled_at_ms": NOW - 1800}]}]}],
    }
    current = deepcopy(previous)
    current.update(snapshot_id="snapshot2", sequence=2,
                   observed_at_ms=NOW - 500, received_at_ms=NOW - 100)
    current["pages"][0]["snapshot_id"] = "snapshot2"
    order = current["pages"][0]["orders"][0]
    order.update(status="FILLED", filled_quantity="2")
    order["fills"].append({"fill_id": "fill2", "quantity": "1",
                           "filled_at_ms": NOW - 700})
    return expected, previous, current


def evaluate(change_previous=None, change_current=None, previous_now_ms=NOW - 1000,
             now_ms=NOW):
    e, p, c = sample()
    if change_previous:
        change_previous(p)
    if change_current:
        change_current(c)
    return inspect_declared_snapshot_transition(e, p, c, previous_now_ms, now_ms)


def test_valid_declared_progression_remains_non_executable():
    result = evaluate()
    assert result["status"] == "DECLARED_TRANSITION_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["previous_census_failed_checks"] == ["unresolved_order_state"]
    assert result["current_census_failed_checks"] == []
    for flag in ("broker_authenticated", "snapshot_completeness_authenticated",
                 "terminal_receipts_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


@pytest.mark.parametrize("change,reason", [
    (lambda c: c.update(snapshot_id="snapshot1", pages=[dict(c["pages"][0], snapshot_id="snapshot1")]), "snapshot_id_reused"),
    (lambda c: c.update(sequence=1), "snapshot_sequence_replay"),
    (lambda c: c.update(observed_at_ms=NOW-1500), "snapshot_time_regression"),
    (lambda c: c.update(received_at_ms=NOW-1200), "snapshot_time_regression"),
    (lambda c: c.update(account_alias="other"), "snapshot_account_changed"),
    (lambda c: c["pages"][0]["orders"][0].update(broker_order_id="broker2"), "broker_order_identity_changed"),
    (lambda c: c["pages"][0]["orders"][0]["fills"].pop(0), "previous_fill_disappeared"),
    (lambda c: c["pages"][0]["orders"][0]["fills"][0].update(filled_at_ms=NOW-1700), "previous_fill_mutated"),
    (lambda c: c["pages"][0]["orders"][0]["fills"][0].update(quantity="0.5"), "previous_fill_mutated"),
    (lambda c: c["pages"][0]["orders"][0].update(filled_quantity="0.5", status="PARTIAL", fills=[{"fill_id":"fill1", "quantity":"0.5", "filled_at_ms":NOW-1800}]), "filled_quantity_decreased"),
    (lambda c: c["pages"][0]["orders"].clear(), "snapshot_order_population_changed"),
])
def test_transition_anomalies_hold(change, reason):
    result = evaluate(change_current=change)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert reason in result["failed_checks"]
    assert result["may_clear_unknown"] is False


def test_terminal_status_change_holds():
    e, p, c = sample()
    p["pages"][0]["orders"][0].update(status="FILLED", filled_quantity="2")
    p["pages"][0]["orders"][0]["fills"].append({"fill_id":"fill2", "quantity":"1", "filled_at_ms":NOW-1500})
    c["pages"][0]["orders"][0].update(status="CANCELLED", filled_quantity="0", fills=[])
    result = inspect_declared_snapshot_transition(e, p, c, NOW-1000, NOW)
    assert "terminal_status_changed" in result["failed_checks"]
    assert result["status"] == "HOLD_RECONCILIATION"


def test_prior_census_invalid_holds_even_if_current_is_clean():
    result = evaluate(change_previous=lambda p: p["pages"][0].update(complete=False))
    assert "previous_census_invalid" in result["failed_checks"]


def test_current_census_invalid_holds_even_if_transition_monotonic():
    result = evaluate(change_current=lambda c: c["pages"][0].update(complete=False))
    assert "current_census_invalid" in result["failed_checks"]


@pytest.mark.parametrize("earlier,later", [(NOW, NOW), (NOW + 1, NOW), (True, NOW)])
def test_trusted_clock_order_holds(earlier, later):
    # A boolean clock is rejected by the underlying strict census.
    if type(earlier) is bool:
        with pytest.raises(ValueError):
            evaluate(previous_now_ms=earlier, now_ms=later)
    else:
        assert "trusted_clock_order" in evaluate(previous_now_ms=earlier, now_ms=later)["failed_checks"]


def test_no_mutation():
    e, p, c = sample()
    original = deepcopy((e, p, c))
    inspect_declared_snapshot_transition(e, p, c, NOW - 1000, NOW)
    assert (e, p, c) == original


def test_decimal_spellings_not_treated_as_changed_fills():
    result = evaluate(change_current=lambda c: c["pages"][0]["orders"][0]["fills"][0].update(quantity="1.0"))
    assert result["failed_checks"] == []


@pytest.mark.parametrize("invalid_sequence", [0, True, -1])
def test_invalid_sequence_schema_fails_closed(invalid_sequence):
    with pytest.raises(ValueError, match="Invalid snapshot sequence"):
        evaluate(change_current=lambda c: c.update(sequence=invalid_sequence))


@pytest.mark.parametrize("backdated_at", [NOW - 1500, NOW - 1400])
def test_newly_disclosed_fill_at_or_before_previous_observation_holds(backdated_at):
    result = evaluate(change_current=lambda c: c["pages"][0]["orders"][0]["fills"][1].update(
        filled_at_ms=backdated_at))
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "retroactive_fill_appearance" in result["failed_checks"]
    assert result["current_census_failed_checks"] == []
    assert result["may_clear_unknown"] is False


@pytest.mark.parametrize("fill_at", [NOW - 1399, NOW - 1001, NOW - 1000])
def test_new_fill_at_or_before_prior_trusted_check_holds(fill_at):
    result = evaluate(change_current=lambda c: c["pages"][0]["orders"][0]["fills"][1].update(
        filled_at_ms=fill_at))
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "fill_predates_prior_trusted_check" in result["failed_checks"]
    assert "retroactive_fill_appearance" not in result["failed_checks"]
    assert result["previous_census_failed_checks"] == ["unresolved_order_state"]
    assert result["current_census_failed_checks"] == []
    assert result["may_clear_unknown"] is False


def test_new_fill_after_prior_trusted_check_is_not_backdated():
    result = evaluate(change_current=lambda c: c["pages"][0]["orders"][0]["fills"][1].update(
        filled_at_ms=NOW - 999))
    assert result["status"] == "DECLARED_TRANSITION_CANDIDATE_UNVERIFIED"
    assert "fill_predates_prior_trusted_check" not in result["failed_checks"]
    assert "retroactive_fill_appearance" not in result["failed_checks"]


@pytest.mark.parametrize("overlapping_observed_at", [NOW - 1150, NOW - 1100])
def test_overlapping_snapshot_observation_and_previous_receipt_holds(overlapping_observed_at):
    def overlap(c):
        c["observed_at_ms"] = overlapping_observed_at
        c["pages"][0]["orders"][0]["fills"][1]["filled_at_ms"] = NOW - 1200
    result = evaluate(change_current=overlap)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "snapshot_observation_overlap" in result["failed_checks"]
    assert "retroactive_fill_appearance" not in result["failed_checks"]
    assert result["current_census_failed_checks"] == []
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("skipped_sequence", [3, 10])
def test_skipped_caller_checkpoint_sequence_holds(skipped_sequence):
    result = evaluate(change_current=lambda c: c.update(sequence=skipped_sequence))
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "snapshot_sequence_gap" in result["failed_checks"]
    assert result["current_census_failed_checks"] == []
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("observed_at", [NOW - 1050, NOW - 1000])
def test_new_observation_not_after_prior_trusted_check_holds(observed_at):
    def adjust(c):
        c["observed_at_ms"] = observed_at
        c["pages"][0]["orders"][0]["fills"][1]["filled_at_ms"] = NOW - 1200
    result = evaluate(change_current=adjust)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "snapshot_observation_precedes_prior_check" in result["failed_checks"]
    assert "snapshot_observation_overlap" not in result["failed_checks"]
    assert result["current_census_failed_checks"] == []
    assert result["may_clear_unknown"] is False


def test_new_observation_after_prior_trusted_check_is_allowed():
    def adjust(c):
        c["observed_at_ms"] = NOW - 999
        c["pages"][0]["orders"][0]["fills"][1]["filled_at_ms"] = NOW - 1001
    result = evaluate(change_current=adjust)
    assert result["status"] == "DECLARED_TRANSITION_CANDIDATE_UNVERIFIED"
    assert "snapshot_observation_precedes_prior_check" not in result["failed_checks"]
