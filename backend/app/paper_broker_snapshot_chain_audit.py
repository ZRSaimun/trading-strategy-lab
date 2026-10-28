"""Offline, caller-declared broker snapshot chain audit; never authorizes orders.

A pairwise fence cannot detect nonadjacent reuse of a snapshot ID. This
bounded diagnostic audits a whole caller-supplied chain without network or IO.
Neither snapshots nor the caller's checkpoint clocks are authenticated.
"""
from __future__ import annotations

from typing import Any

from app.paper_broker_inventory_census import inspect_declared_inventory
from app.paper_broker_snapshot_replay_fence import inspect_declared_snapshot_transition

MAX_CHAIN_SNAPSHOTS = 16
MAX_CHECKPOINT_GAP_MS = 60_000
_ALLOWED_INTERMEDIATE_FAILURES = frozenset({"unresolved_order_state"})


def inspect_declared_snapshot_chain(expected: dict, snapshots: list[dict],
                                    check_times_ms: list[int],
                                    max_checkpoint_gap_ms: int = MAX_CHECKPOINT_GAP_MS) -> dict[str, Any]:
    """Fail closed on replay/gaps across 2..16 declared broker snapshots.

    Intermediate OPEN/PARTIAL inventories are allowed *only* as diagnostics.
    The final census must be terminal and otherwise clean. Each adjacent pair
    is checked by the replay fence; nonadjacent ID reuse is checked globally.
    Schema errors raise ValueError. No successful result clears UNKNOWN orders.
    """
    if type(snapshots) is not list or not 2 <= len(snapshots) <= MAX_CHAIN_SNAPSHOTS:
        raise ValueError("Invalid snapshot chain length")
    if type(check_times_ms) is not list or len(check_times_ms) != len(snapshots):
        raise ValueError("Invalid snapshot chain check times")

    if (type(max_checkpoint_gap_ms) is not int or
            not 1 <= max_checkpoint_gap_ms <= MAX_CHECKPOINT_GAP_MS):
        raise ValueError("Invalid maximum checkpoint gap")

    failures: set[str] = set()
    seen_snapshot_ids: set[str] = set()
    transitions: list[dict[str, Any]] = []
    last = len(snapshots) - 1
    for i, snapshot in enumerate(snapshots):
        census = inspect_declared_inventory(expected, snapshot, check_times_ms[i])
        census_failures = set(census["failed_checks"])
        if i < last:
            if census_failures - _ALLOWED_INTERMEDIATE_FAILURES:
                failures.add("intermediate_census_invalid")
        elif census_failures:
            failures.add("final_census_invalid")

        snapshot_id = snapshot["snapshot_id"]  # schema-validated by census
        if snapshot_id in seen_snapshot_ids:
            failures.add("snapshot_id_reused_in_chain")
        seen_snapshot_ids.add(snapshot_id)

        if i:
            # Fresh individual snapshots do not prove continuous monitoring.
            # Reject long blind intervals even when caller sequence numbers
            # remain contiguous and both individual censuses appear fresh.
            if check_times_ms[i] - check_times_ms[i - 1] > max_checkpoint_gap_ms:
                failures.add("trusted_checkpoint_gap")
            if (snapshot["observed_at_ms"] - snapshots[i - 1]["observed_at_ms"]
                    > max_checkpoint_gap_ms):
                failures.add("snapshot_observation_gap")
            result = inspect_declared_snapshot_transition(
                expected, snapshots[i - 1], snapshot,
                check_times_ms[i - 1], check_times_ms[i])
            pair_failures = set(result["failed_checks"])
            if (i < last and
                    set(result["current_census_failed_checks"]) == _ALLOWED_INTERMEDIATE_FAILURES):
                # The pairwise fence expects a terminal *current* inventory;
                # in a chain, intermediate unresolved states are intentional.
                pair_failures.discard("current_census_invalid")
            failures.update(pair_failures)
            transitions.append({"to_snapshot_index": i,
                                "failed_checks": sorted(pair_failures)})

    return {
        "status": ("HOLD_RECONCILIATION" if failures
                   else "DECLARED_CHAIN_CANDIDATE_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "snapshot_count": len(snapshots),
        "transitions": transitions,
        "broker_authenticated": False,
        "snapshot_completeness_authenticated": False,
        "terminal_receipts_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
