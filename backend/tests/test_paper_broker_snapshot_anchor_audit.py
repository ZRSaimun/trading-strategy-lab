"""Offline, synthetic anchor integrity tests; no broker access."""
from copy import deepcopy

import pytest

from app.paper_broker_snapshot_anchor_audit import (
    fingerprint_declared_chain,
    fingerprint_declared_snapshot,
    inspect_declared_snapshot_anchors,
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
    final_order = final["pages"][0]["orders"][0]
    final_order.update(status="FILLED", filled_quantity="2")
    final_order["fills"].append({"fill_id": "fill2", "quantity": "1",
                                 "filled_at_ms": NOW - 2000})
    return expected, [first, final], [NOW - 3800, NOW]


def anchored():
    expected, snapshots, clocks = fixture()
    digests = [fingerprint_declared_snapshot(snapshot) for snapshot in snapshots]
    return expected, snapshots, clocks, digests, fingerprint_declared_chain(digests)


def test_unchanged_declared_chain_remains_unverified_and_non_executable():
    result = inspect_declared_snapshot_anchors(*anchored())
    assert result["status"] == "DECLARED_ANCHOR_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["snapshot_count"] == 2
    for flag in ("broker_authenticated", "anchor_custody_authenticated",
                 "snapshot_completeness_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


def test_prior_snapshot_mutation_detected_even_when_chain_still_semantically_valid():
    args = list(anchored())
    args[1][0]["pages"][0]["orders"][0]["fills"][0]["quantity"] = "1.0"
    result = inspect_declared_snapshot_anchors(*args)
    assert "snapshot_digest_mismatch" in result["failed_checks"]
    assert "chain_digest_mismatch" in result["failed_checks"]
    assert result["may_clear_unknown"] is False


def test_snapshot_reordering_fails_closed():
    args = list(anchored())
    args[1].reverse()
    result = inspect_declared_snapshot_anchors(*args)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert "snapshot_digest_mismatch" in result["failed_checks"]
    assert "chain_digest_mismatch" in result["failed_checks"]


def test_chain_anchor_mismatch_without_snapshot_mismatch():
    args = list(anchored())
    args[4] = "b" * 64
    result = inspect_declared_snapshot_anchors(*args)
    assert result["failed_checks"] == ["chain_digest_mismatch"]


def test_prior_anchor_mismatch_without_chain_mismatch():
    args = list(anchored())
    args[3][0] = "b" * 64
    result = inspect_declared_snapshot_anchors(*args)
    assert result["failed_checks"] == ["snapshot_digest_mismatch"]


def test_canonical_json_key_order_does_not_change_digest():
    _, snapshots, _ = fixture()
    original = snapshots[0]
    reordered = dict(reversed(list(original.items())))
    assert fingerprint_declared_snapshot(original) == fingerprint_declared_snapshot(reordered)


def test_chain_fingerprint_binds_order():
    a, b = "a" * 64, "b" * 64
    assert fingerprint_declared_chain([a, b]) != fingerprint_declared_chain([b, a])


@pytest.mark.parametrize("bad", [None, "a" * 63, "A" * 64, "0" * 64, True, 7])
def test_invalid_prior_chain_digest_rejected(bad):
    args = list(anchored())
    args[4] = bad
    with pytest.raises(ValueError, match="Invalid prior chain digest"):
        inspect_declared_snapshot_anchors(*args)


@pytest.mark.parametrize("bad", [[], ["a" * 64], ["a" * 64] * 17, ("a" * 64,) * 2])
def test_invalid_prior_digest_population_rejected(bad):
    args = list(anchored())
    args[3] = bad
    with pytest.raises(ValueError, match="Invalid prior snapshot digest population"):
        inspect_declared_snapshot_anchors(*args)


def test_count_mismatch_rejected():
    args = list(anchored())
    args[3].append("b" * 64)
    with pytest.raises(ValueError, match="Prior digest count"):
        inspect_declared_snapshot_anchors(*args)


def test_underlying_replay_failures_remain_holds_with_matching_anchors():
    args = list(anchored())
    args[1][1]["sequence"] = 3
    args[3] = [fingerprint_declared_snapshot(s) for s in args[1]]
    args[4] = fingerprint_declared_chain(args[3])
    result = inspect_declared_snapshot_anchors(*args)
    assert "snapshot_sequence_gap" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_input_not_mutated():
    args = anchored()
    before = deepcopy(args)
    inspect_declared_snapshot_anchors(*args)
    assert args == before


def test_non_json_snapshot_rejected_by_fingerprint():
    with pytest.raises(ValueError, match="Snapshot is not canonical JSON"):
        fingerprint_declared_snapshot({"bad": object()})
