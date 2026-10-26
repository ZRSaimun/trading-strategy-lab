"""Synthetic snapshot continuity checks; never authenticate broker receipts."""
import copy
import random

import pytest

from app.offline_demo_order_receipt_replay import fingerprint_demo_order_event
from app.offline_demo_receipt_snapshot_continuity import (
    audit_declared_demo_receipt_snapshot_continuity as audit,
)

ZERO = "0" * 64
IDENTITY = ("provider", "venue", "account_alias", "instrument", "client_order_id")


def scope(as_of=200, requested=5):
    return dict(provider="Synthetic", venue="DEMO", account_alias="account-1",
                instrument="XAUUSD-CFD", client_order_id="order-1", side="BUY",
                requested_contracts=requested, submitted_at_ms=100,
                as_of_ms=as_of, intent_sha256="a" * 64)


def history(s, specs):
    events = []
    head = ZERO
    for n, (kind, occurred, received, qty, broker) in enumerate(specs, 1):
        e = dict(sequence=n, event_id=f"event-{n}", kind=kind,
                 occurred_at_ms=occurred, received_at_ms=received,
                 broker_order_id=broker, contracts=qty,
                 receipt_sha256=f"{n:064x}", previous_event_sha256=head,
                 **{key: s[key] for key in IDENTITY})
        events.append(e)
        head = fingerprint_demo_order_event(s, e)
    return events, dict(expected_event_count=len(events),
                        expected_head_sha256=head,
                        manifest_recorded_at_ms=max(e["received_at_ms"] for e in events))


def snapshots():
    old = scope()
    new = scope(as_of=400)
    first = [("SUBMITTED", 100, 101, 0, None),
             ("ACCEPTED", 110, 111, 0, "broker-1"),
             ("FILL", 120, 121, 2, "broker-1")]
    later = first + [("FILL", 220, 221, 1, "broker-1")]
    old_events, old_manifest = history(old, first)
    new_events, new_manifest = history(new, later)
    return old, old_events, old_manifest, new, new_events, new_manifest


def test_valid_append_only_partial_fills_never_authorizes_orders():
    result = audit(*snapshots())
    assert result["status"] == "DECLARED_CONTINUITY_ONLY"
    assert result["previous_unique_receipts"] == 3
    assert result["current_unique_receipts"] == 4
    assert result["new_declared_receipts"] == 1
    assert result["previous_declared_filled_contracts"] == 2
    assert result["current_declared_filled_contracts"] == 3
    assert result["current_declared_remaining_contracts"] == 2
    assert result["manual_broker_reconciliation_required"]
    assert not result["broker_receipts_authenticated"]
    assert not result["external_population_completeness_verified"]
    assert not result["durable_transactional_storage_provided"]
    assert not result["may_execute_demo_order"] and not result["may_execute_real_order"]
    assert result == audit(*snapshots())


def test_same_history_later_cutoff_is_valid_but_not_broker_verified():
    args = list(snapshots())
    args[4] = copy.deepcopy(args[1])
    args[5] = copy.deepcopy(args[2])
    result = audit(*args)
    assert result["new_declared_receipts"] == 0
    assert result["current_declared_filled_contracts"] == 2
    assert result["manual_broker_reconciliation_required"]


def test_exact_duplicate_deliveries_are_idempotent():
    args = list(snapshots())
    original = audit(*args)
    args[1] = [args[1][0], args[1][0], *args[1][1:]]
    args[4] = [args[4][0], args[4][0], *args[4][1:3], args[4][2], args[4][3]]
    assert audit(*args) == original


@pytest.mark.parametrize("field,replacement", [
    ("provider", "Other"), ("venue", "LIVE"), ("account_alias", "other"),
    ("instrument", "NSXUSD"), ("client_order_id", "other"),
    ("side", "SELL"), ("requested_contracts", 6),
    ("submitted_at_ms", 99), ("intent_sha256", "b" * 64),
])
def test_immutable_order_identity_cannot_change(field, replacement):
    args = list(snapshots())
    args[3][field] = replacement
    if field in IDENTITY or field == "submitted_at_ms":
        # Keep the new snapshot internally valid where possible, then test
        # the cross-snapshot immutability check itself.
        specs = [(e["kind"], e["occurred_at_ms"], e["received_at_ms"],
                  e["contracts"], e["broker_order_id"]) for e in args[4]]
        if field == "submitted_at_ms":
            specs[0] = ("SUBMITTED", 99, 101, 0, None)
        args[4], args[5] = history(args[3], specs)
    elif field in ("intent_sha256", "requested_contracts", "side"):
        specs = [(e["kind"], e["occurred_at_ms"], e["received_at_ms"],
                  e["contracts"], e["broker_order_id"]) for e in args[4]]
        args[4], args[5] = history(args[3], specs)
    with pytest.raises(ValueError):
        audit(*args)


def test_current_cutoff_must_strictly_advance():
    args = list(snapshots())
    args[3]["as_of_ms"] = args[0]["as_of_ms"]
    with pytest.raises(ValueError):
        audit(*args)


def test_previous_prefix_rewrite_rejected_even_with_recomputed_chain():
    args = list(snapshots())
    specs = [("SUBMITTED", 100, 101, 0, None),
             ("ACCEPTED", 110, 111, 0, "broker-1"),
             ("FILL", 120, 121, 1, "broker-1"),
             ("FILL", 220, 221, 2, "broker-1")]
    args[4], args[5] = history(args[3], specs)
    with pytest.raises(ValueError, match="prefix changed"):
        audit(*args)


def test_missing_previous_receipt_rejected():
    args = list(snapshots())
    args[4], args[5] = history(args[3], [
        ("SUBMITTED", 100, 101, 0, None),
        ("ACCEPTED", 110, 111, 0, "broker-1")])
    with pytest.raises(ValueError, match="omitted"):
        audit(*args)


def test_pre_cutoff_backfill_rejected_even_if_upstream_replay_accepts_it():
    args = list(snapshots())
    specs = [("SUBMITTED", 100, 101, 0, None),
             ("ACCEPTED", 110, 111, 0, "broker-1"),
             ("FILL", 120, 121, 2, "broker-1"),
             ("FILL", 130, 150, 1, "broker-1")]
    args[4], args[5] = history(args[3], specs)
    with pytest.raises(ValueError, match="pre-cutoff"):
        audit(*args)


def test_later_manifest_must_not_precede_prior_manifest():
    args = list(snapshots())
    args[4] = copy.deepcopy(args[1])
    args[5] = copy.deepcopy(args[2])
    args[2]["manifest_recorded_at_ms"] = 190
    args[5]["manifest_recorded_at_ms"] = 180
    with pytest.raises(ValueError, match="predate previous"):
        audit(*args)


def test_malformed_receipts_fail_closed_via_upstream_replay():
    args = list(snapshots())
    args[4][3]["contracts"] = 10
    with pytest.raises(ValueError):
        audit(*args)
    args = list(snapshots())
    args[5]["expected_head_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        audit(*args)


def test_cancel_race_keeps_partial_exposure():
    args = list(snapshots())
    specs = [("SUBMITTED", 100, 101, 0, None),
             ("ACCEPTED", 110, 111, 0, "broker-1"),
             ("FILL", 120, 121, 2, "broker-1"),
             ("CANCEL_REQUESTED", 220, 221, 0, "broker-1"),
             ("FILL", 230, 231, 1, "broker-1"),
             ("CANCELED", 240, 241, 0, "broker-1")]
    args[4], args[5] = history(args[3], specs)
    assert audit(*args)["current_declared_filled_contracts"] == 3
    assert audit(*args)["current_declared_remaining_contracts"] == 2


def test_seeded_randomized_append_only_partitions():
    rng = random.Random(20261026)
    for _ in range(200):
        requested = rng.randint(2, 100)
        before = rng.randint(1, requested - 1)
        after = rng.randint(1, requested - before)
        old = scope(requested=requested)
        new = scope(as_of=400, requested=requested)
        prefix = [("SUBMITTED", 100, 101, 0, None),
                  ("ACCEPTED", 110, 111, 0, "broker-1"),
                  ("FILL", 120, 121, before, "broker-1")]
        prior_events, prior_manifest = history(old, prefix)
        next_events, next_manifest = history(new, prefix + [
            ("FILL", 220, 221, after, "broker-1")])
        result = audit(old, prior_events, prior_manifest,
                       new, next_events, next_manifest)
        assert result["current_declared_filled_contracts"] == before + after
        assert result["current_declared_remaining_contracts"] == requested - before - after
        assert result["new_declared_receipts"] == 1
