"""Synthetic, disconnected regression tests for multi-snapshot replay detection."""
from copy import deepcopy

import pytest

from app.paper_broker_snapshot_chain_audit import inspect_declared_snapshot_chain

NOW = 1_800_000_000_000


def sample():
    expected = {
        "broker": "T212-INVEST-DEMO", "account_alias": "demo-account",
        "max_snapshot_age_ms": 5000, "max_transport_lag_ms": 2000,
        "unresolved_orders": [{"client_order_id": "client1", "intent_sha": "a" * 64,
                               "instrument": "ABC", "side": "BUY", "quantity": "2",
                               "attempted_at_ms": NOW - 5000}],
    }
    first = {
        "broker": "T212-INVEST-DEMO", "account_alias": "demo-account",
        "snapshot_id": "snapshot1", "sequence": 1,
        "observed_at_ms": NOW - 4000, "received_at_ms": NOW - 3900,
        "pages": [{"snapshot_id": "snapshot1", "index": 0, "total_pages": 1,
                   "complete": True,
                   "orders": [{"client_order_id": "client1", "broker_order_id": "broker1",
                               "instrument": "ABC", "side": "BUY", "quantity": "2",
                               "status": "PARTIAL", "filled_quantity": "1",
                               "fills": [{"fill_id": "fill1", "quantity": "1",
                                          "filled_at_ms": NOW - 4500}]}]}],
    }
    middle = deepcopy(first)
    middle.update(snapshot_id="snapshot2", sequence=2,
                  observed_at_ms=NOW - 2500, received_at_ms=NOW - 2400)
    middle["pages"][0]["snapshot_id"] = "snapshot2"
    final = deepcopy(middle)
    final.update(snapshot_id="snapshot3", sequence=3,
                 observed_at_ms=NOW - 1000, received_at_ms=NOW - 900)
    final["pages"][0]["snapshot_id"] = "snapshot3"
    final_order = final["pages"][0]["orders"][0]
    final_order.update(status="FILLED", filled_quantity="2")
    final_order["fills"].append({"fill_id": "fill2", "quantity": "1",
                                 "filled_at_ms": NOW - 2000})
    return expected, [first, middle, final], [NOW - 3800, NOW - 2300, NOW]


def evaluate(change=None):
    expected, snapshots, clocks = sample()
    if change:
        change(snapshots, clocks)
    return inspect_declared_snapshot_chain(expected, snapshots, clocks)


def test_clean_three_checkpoint_chain_remains_unverified_and_non_executable():
    result = evaluate()
    assert result["status"] == "DECLARED_CHAIN_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["snapshot_count"] == 3
    assert result["transitions"] == [
        {"to_snapshot_index": 1, "failed_checks": []},
        {"to_snapshot_index": 2, "failed_checks": []},
    ]
    for flag in ("broker_authenticated", "snapshot_completeness_authenticated",
                 "terminal_receipts_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


def test_nonadjacent_snapshot_id_reuse_holds_even_when_pairwise_ids_differ():
    def replay(snapshots, clocks):
        snapshots[2]["snapshot_id"] = "snapshot1"
        snapshots[2]["pages"][0]["snapshot_id"] = "snapshot1"
    result = evaluate(replay)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "snapshot_id_reused_in_chain" in result["failed_checks"]
    assert all(not t["failed_checks"] for t in result["transitions"])
    assert result["may_clear_unknown"] is False


def test_adjacent_snapshot_id_reuse_holds():
    def replay(snapshots, clocks):
        snapshots[1]["snapshot_id"] = "snapshot1"
        snapshots[1]["pages"][0]["snapshot_id"] = "snapshot1"
    result = evaluate(replay)
    assert "snapshot_id_reused_in_chain" in result["failed_checks"]
    assert "snapshot_id_reused" in result["failed_checks"]


def test_intermediate_invalid_census_holds():
    result = evaluate(lambda snapshots, clocks: snapshots[1]["pages"][0].update(complete=False))
    assert "intermediate_census_invalid" in result["failed_checks"]
    assert result["status"] == "HOLD_RECONCILIATION"


def test_final_nonterminal_inventory_holds():
    def leave_unresolved(snapshots, clocks):
        snapshots[2]["pages"][0]["orders"][0] = deepcopy(snapshots[1]["pages"][0]["orders"][0])
    result = evaluate(leave_unresolved)
    assert "final_census_invalid" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_skipped_sequence_holds():
    result = evaluate(lambda snapshots, clocks: snapshots[2].update(sequence=4))
    assert "snapshot_sequence_gap" in result["failed_checks"]


def test_missing_prior_fill_holds():
    def omit(snapshots, clocks):
        snapshots[2]["pages"][0]["orders"][0]["fills"].pop(0)
    result = evaluate(omit)
    assert "previous_fill_disappeared" in result["failed_checks"]


def test_nonmonotonic_trusted_check_time_holds():
    result = evaluate(lambda snapshots, clocks: clocks.__setitem__(2, clocks[1]))
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "trusted_clock_order" in result["failed_checks"]


@pytest.mark.parametrize("invalid_snapshots,invalid_clocks", [
    ([], []), ([{}], [NOW]), ([{}] * 17, [NOW] * 17),
    ((), ()), ([{}, {}], [NOW]), ([{}, {}], (NOW, NOW)),
])
def test_invalid_chain_shape_rejected(invalid_snapshots, invalid_clocks):
    expected, _, _ = sample()
    with pytest.raises(ValueError, match="Invalid snapshot chain"):
        inspect_declared_snapshot_chain(expected, invalid_snapshots, invalid_clocks)


def test_invalid_snapshot_schema_rejected():
    expected, snapshots, clocks = sample()
    snapshots[1]["sequence"] = True
    with pytest.raises(ValueError, match="Invalid snapshot sequence"):
        inspect_declared_snapshot_chain(expected, snapshots, clocks)


def test_input_not_mutated():
    expected, snapshots, clocks = sample()
    before = deepcopy((expected, snapshots, clocks))
    inspect_declared_snapshot_chain(expected, snapshots, clocks)
    assert (expected, snapshots, clocks) == before


def test_large_blind_interval_holds_despite_fresh_individual_censuses():
    expected, snapshots, clocks = sample()
    delta = 60_001
    for field in ("observed_at_ms", "received_at_ms"):
        snapshots[2][field] += delta
    clocks[2] += delta
    result = inspect_declared_snapshot_chain(expected, snapshots, clocks)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "trusted_checkpoint_gap" in result["failed_checks"]
    assert "snapshot_observation_gap" in result["failed_checks"]
    assert result["transitions"][-1]["failed_checks"] == []
    assert result["may_clear_unknown"] is False


def test_observation_gap_holds_even_when_checkpoints_meet_policy():
    expected, snapshots, clocks = sample()
    snapshots[1]["observed_at_ms"] = NOW - 3500
    result = inspect_declared_snapshot_chain(
        expected, snapshots, clocks, max_checkpoint_gap_ms=2400)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "snapshot_observation_gap" in result["failed_checks"]
    assert "trusted_checkpoint_gap" not in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_checkpoint_gap_exact_policy_boundary_is_accepted_but_unverified():
    expected, snapshots, clocks = sample()
    result = inspect_declared_snapshot_chain(
        expected, snapshots, clocks, max_checkpoint_gap_ms=2300)
    assert result["status"] == "DECLARED_CHAIN_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["may_clear_unknown"] is False


def test_checkpoint_gap_over_custom_policy_holds():
    expected, snapshots, clocks = sample()
    result = inspect_declared_snapshot_chain(
        expected, snapshots, clocks, max_checkpoint_gap_ms=2299)
    assert "trusted_checkpoint_gap" in result["failed_checks"]
    assert result["status"] == "HOLD_RECONCILIATION"


@pytest.mark.parametrize("invalid_gap", [0, -1, True, 60_001, "5000", 1.5])
def test_invalid_checkpoint_gap_policy_rejected(invalid_gap):
    expected, snapshots, clocks = sample()
    with pytest.raises(ValueError, match="Invalid maximum checkpoint gap"):
        inspect_declared_snapshot_chain(
            expected, snapshots, clocks, max_checkpoint_gap_ms=invalid_gap)
