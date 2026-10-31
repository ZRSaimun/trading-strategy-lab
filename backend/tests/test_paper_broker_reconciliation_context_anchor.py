"""Synthetic-only broker reconciliation context custody tests; no network."""
from copy import deepcopy

import pytest

from app.paper_broker_snapshot_anchor_audit import (
    fingerprint_declared_chain, fingerprint_declared_snapshot,
)
from app.paper_broker_reconciliation_context_anchor import (
    fingerprint_declared_reconciliation_context,
    inspect_declared_reconciliation_context_anchors,
)

NOW = 1_800_000_000_000


def fixture():
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
    final = deepcopy(first)
    final.update(snapshot_id="snapshot2", sequence=2,
                 observed_at_ms=NOW - 1000, received_at_ms=NOW - 900)
    final["pages"][0]["snapshot_id"] = "snapshot2"
    order = final["pages"][0]["orders"][0]
    order.update(status="FILLED", filled_quantity="2")
    order["fills"].append({"fill_id": "fill2", "quantity": "1",
                           "filled_at_ms": NOW - 2000})
    return expected, [first, final], [NOW - 3800, NOW]


def anchored():
    expected, snapshots, clocks = fixture()
    hashes = [fingerprint_declared_snapshot(s) for s in snapshots]
    chain = fingerprint_declared_chain(hashes)
    context = fingerprint_declared_reconciliation_context(expected, clocks)
    return expected, snapshots, clocks, hashes, chain, context


def test_clean_context_remains_unverified_and_non_executable():
    result = inspect_declared_reconciliation_context_anchors(*anchored())
    assert result["status"] == "DECLARED_CONTEXT_ANCHOR_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["snapshot_count"] == 2
    for flag in ("broker_authenticated", "context_custody_authenticated",
                 "anchor_custody_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


def test_intent_fingerprint_swap_caught_even_when_snapshots_unchanged():
    args = list(anchored())
    args[0]["unresolved_orders"][0]["intent_sha"] = "b" * 64
    result = inspect_declared_reconciliation_context_anchors(*args)
    assert result["failed_checks"] == ["reconciliation_context_digest_mismatch"]
    assert result["status"] == "HOLD_RECONCILIATION"


def test_attempt_timestamp_change_caught():
    args = list(anchored())
    args[0]["unresolved_orders"][0]["attempted_at_ms"] -= 100
    result = inspect_declared_reconciliation_context_anchors(*args)
    assert "reconciliation_context_digest_mismatch" in result["failed_checks"]


def test_freshness_policy_change_caught():
    args = list(anchored())
    args[0]["max_snapshot_age_ms"] = 6000
    result = inspect_declared_reconciliation_context_anchors(*args)
    assert "reconciliation_context_digest_mismatch" in result["failed_checks"]


def test_checkpoint_clock_change_caught_without_replay_error():
    args = list(anchored())
    args[2][0] += 100
    result = inspect_declared_reconciliation_context_anchors(*args)
    assert result["failed_checks"] == ["reconciliation_context_digest_mismatch"]


def test_gap_policy_change_caught_even_when_both_policies_pass():
    args = anchored()
    result = inspect_declared_reconciliation_context_anchors(
        *args, max_checkpoint_gap_ms=30_000)
    assert result["failed_checks"] == ["reconciliation_context_digest_mismatch"]


def test_underlying_snapshot_mutation_still_holds():
    args = list(anchored())
    args[1][0]["pages"][0]["orders"][0]["fills"][0]["quantity"] = "1.0"
    result = inspect_declared_reconciliation_context_anchors(*args)
    assert "snapshot_digest_mismatch" in result["failed_checks"]
    assert "chain_digest_mismatch" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_underlying_invalid_chain_still_holds_with_matching_new_hashes():
    args = list(anchored())
    args[1][1]["sequence"] = 3
    args[3] = [fingerprint_declared_snapshot(s) for s in args[1]]
    args[4] = fingerprint_declared_chain(args[3])
    result = inspect_declared_reconciliation_context_anchors(*args)
    assert "snapshot_sequence_gap" in result["failed_checks"]


def test_context_digest_independent_of_json_key_insertion_order():
    expected, _, clocks = fixture()
    reversed_keys = dict(reversed(list(expected.items())))
    assert (fingerprint_declared_reconciliation_context(expected, clocks)
            == fingerprint_declared_reconciliation_context(reversed_keys, clocks))


def test_context_digest_binds_checkpoint_order_and_gap_policy():
    expected, _, clocks = fixture()
    base = fingerprint_declared_reconciliation_context(expected, clocks)
    assert base != fingerprint_declared_reconciliation_context(expected, clocks, 30_000)
    assert base != fingerprint_declared_reconciliation_context(expected, [clocks[0] - 1, clocks[1]])


@pytest.mark.parametrize("bad", [None, True, 7, "0" * 64, "A" * 64, "a" * 63])
def test_invalid_prior_context_digest_fails_closed(bad):
    args = list(anchored())
    args[5] = bad
    with pytest.raises(ValueError, match="Invalid prior reconciliation context digest"):
        inspect_declared_reconciliation_context_anchors(*args)


@pytest.mark.parametrize("bad", [None, {}, [1], [1] * 17, (1, 2), [True, 2],
                                      [1, 1], [2, 1], [1, "2"]])
def test_invalid_checkpoint_population_fails_closed(bad):
    expected, _, _ = fixture()
    with pytest.raises(ValueError, match="checkpoint"):
        fingerprint_declared_reconciliation_context(expected, bad)


@pytest.mark.parametrize("bad", [0, -1, True, "60000", 60_001, 1.5])
def test_invalid_gap_policy_fails_closed(bad):
    expected, _, clocks = fixture()
    with pytest.raises(ValueError, match="Invalid declared gap policy"):
        fingerprint_declared_reconciliation_context(expected, clocks, bad)


def test_non_json_context_rejected():
    expected, _, clocks = fixture()
    expected["unresolved_orders"][0]["intent_sha"] = object()
    with pytest.raises(ValueError, match="Context is not canonical JSON"):
        fingerprint_declared_reconciliation_context(expected, clocks)


def test_large_context_rejected():
    expected, _, clocks = fixture()
    expected["extra"] = "x" * 270_000
    with pytest.raises(ValueError, match="too large"):
        fingerprint_declared_reconciliation_context(expected, clocks)


def test_inputs_not_mutated():
    args = anchored()
    before = deepcopy(args)
    inspect_declared_reconciliation_context_anchors(*args)
    assert args == before
