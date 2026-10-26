"""Synthetic only: receipt replay does not establish actual broker state."""
import copy
import random

import pytest

from app.offline_demo_order_receipt_replay import (
    fingerprint_demo_order_event, replay_declared_demo_order_receipts,
)

ZERO = "0" * 64


def scope():
    return dict(provider="Synthetic", venue="DEMO", account_alias="a1",
                instrument="XAUUSD-CFD", client_order_id="id-001", side="BUY",
                requested_contracts=5, submitted_at_ms=100, as_of_ms=1000,
                intent_sha256="a" * 64)


def make_events(s=None, specs=None):
    s = s or scope()
    specs = specs if specs is not None else [
        ("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "broker-1"),
        ("FILL", 120, 2, "broker-1"), ("CANCEL_REQUESTED", 130, 0, "broker-1"),
        ("FILL", 140, 1, "broker-1"), ("CANCELED", 150, 0, "broker-1")]
    events = []
    prev = ZERO
    for n, (kind, time, qty, broker) in enumerate(specs, 1):
        event = dict(sequence=n, event_id=f"evt-{n}", kind=kind,
                     occurred_at_ms=time, received_at_ms=time + 1,
                     broker_order_id=broker, contracts=qty,
                     receipt_sha256=f"{n:064x}", previous_event_sha256=prev,
                     **{k: s[k] for k in ("provider", "venue", "account_alias", "instrument", "client_order_id")})
        events.append(event)
        prev = fingerprint_demo_order_event(s, event)
    manifest = dict(expected_event_count=len(events), expected_head_sha256=prev,
                    manifest_recorded_at_ms=max(200, events[-1]["received_at_ms"]))
    return events, manifest


def run(s=None, events=None, manifest=None):
    s = s or scope()
    if events is None:
        events, default_manifest = make_events(s)
    else:
        default_manifest = None
    return replay_declared_demo_order_receipts(s, events, manifest or default_manifest)


def test_partial_fill_cancel_race_preserves_exposure_and_never_permits_orders():
    x = run()
    assert x["status"] == "DECLARED_CANCELED_EXPOSURE_UNVERIFIED"
    assert x["declared_filled_contracts"] == 3
    assert x["declared_remaining_contracts"] == 2
    assert x["unique_receipts"] == 6
    assert x["manual_broker_reconciliation_required"]
    assert not x["may_execute_demo_order"] and not x["may_execute_real_order"]
    assert x == run()


def test_exact_duplicate_delivery_is_idempotent():
    events, manifest = make_events()
    x = run(events=events, manifest=manifest)
    duplicated = [events[0], events[0], *events[1:4], events[3], *events[4:]]
    y = run(events=duplicated, manifest=manifest)
    assert y["duplicate_deliveries_ignored"] == 2
    assert y["head_sha256"] == x["head_sha256"]
    assert y["declared_filled_contracts"] == x["declared_filled_contracts"]


def test_duplicate_conflict_rejected():
    events, manifest = make_events()
    conflict = copy.deepcopy(events[2]); conflict["contracts"] = 4
    with pytest.raises(ValueError, match="Conflicting"):
        run(events=[*events[:3], conflict, *events[3:]], manifest=manifest)


def test_missing_sequence_and_tail_rejected():
    events, manifest = make_events()
    with pytest.raises(ValueError, match="nonconsecutive"):
        run(events=[*events[:2], *events[3:]], manifest=manifest)
    with pytest.raises(ValueError, match="Incomplete"):
        run(events=events[:-1], manifest=manifest)


def test_reordered_events_and_duplicate_event_id_rejected():
    events, manifest = make_events()
    with pytest.raises(ValueError, match="nonconsecutive"):
        run(events=[events[1], events[0], *events[2:]], manifest=manifest)
    events[2]["event_id"] = events[1]["event_id"]
    with pytest.raises(ValueError, match="Reused"):
        run(events=events, manifest=manifest)


def test_hash_chain_and_head_tampering_rejected():
    events, manifest = make_events()
    events[2]["contracts"] = 3
    with pytest.raises(ValueError, match="hash chain"):
        run(events=events, manifest=manifest)
    events, manifest = make_events()
    manifest["expected_head_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="head differs"):
        run(events=events, manifest=manifest)


def test_replayed_same_receipts_with_different_intent_digest_rejected():
    events, manifest = make_events()
    s = scope(); s["intent_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="hash chain"):
        run(s=s, events=events, manifest=manifest)


def test_full_fill_is_unverified_not_broker_confirmation():
    specs = [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"),
             ("FILL", 120, 2, "b"), ("FILL", 130, 3, "b")]
    events, manifest = make_events(specs=specs)
    x = run(events=events, manifest=manifest)
    assert x["status"] == "DECLARED_FULL_FILL_UNVERIFIED"
    assert x["declared_remaining_contracts"] == 0
    assert x["manual_broker_reconciliation_required"]


@pytest.mark.parametrize("specs,status", [
    ([("SUBMITTED", 100, 0, None)], "SUBMISSION_EXPOSURE_UNKNOWN"),
    ([("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b")], "ACCEPTED_EXPOSURE_UNKNOWN"),
    ([("SUBMITTED", 100, 0, None), ("CANCEL_REQUESTED", 110, 0, None)], "CANCEL_PENDING_EXPOSURE_UNKNOWN"),
    ([("SUBMITTED", 100, 0, None), ("REJECTED", 110, 0, None)], "DECLARED_REJECTED_EXPOSURE_UNVERIFIED"),
    ([("SUBMITTED", 100, 0, None), ("EXPIRED", 110, 0, None)], "DECLARED_EXPIRED_EXPOSURE_UNVERIFIED"),
])
def test_unverified_statuses(specs, status):
    events, manifest = make_events(specs=specs)
    assert run(events=events, manifest=manifest)["status"] == status


@pytest.mark.parametrize("specs", [
    [("ACCEPTED", 100, 0, "b")],
    [("SUBMITTED", 100, 0, None), ("SUBMITTED", 110, 0, None)],
    [("SUBMITTED", 100, 0, None), ("FILL", 110, 1, "b")],
    [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"), ("ACCEPTED", 120, 0, "b")],
    [("SUBMITTED", 100, 0, None), ("CANCELED", 110, 0, "b")],
    [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"), ("CANCELED", 120, 0, "b")],
    [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"), ("FILL", 120, 6, "b")],
    [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"), ("FILL", 120, 5, "b"), ("CANCEL_REQUESTED", 130, 0, "b")],
    [("SUBMITTED", 100, 0, None), ("REJECTED", 110, 0, None), ("ACCEPTED", 120, 0, "b")],
    [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"), ("CANCEL_REQUESTED", 120, 0, "b"), ("CANCELED", 130, 0, "b"), ("FILL", 140, 1, "b")],
    [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b"), ("FILL", 120, 1, "other")],
    [("SUBMITTED", 100, 0, None), ("CANCEL_REQUESTED", 110, 0, None), ("ACCEPTED", 120, 0, "b")],
])
def test_illegal_state_transitions_fail_closed(specs):
    events, manifest = make_events(specs=specs)
    with pytest.raises(ValueError):
        run(events=events, manifest=manifest)


@pytest.mark.parametrize("field,value", [
    ("provider", "Bad source"), ("side", "LONG"), ("requested_contracts", 0),
    ("requested_contracts", True), ("as_of_ms", 99), ("intent_sha256", "BAD"),
    ("submitted_at_ms", 1001), ("instrument", ""),
])
def test_invalid_scope_rejected(field, value):
    s = scope(); s[field] = value
    with pytest.raises(ValueError):
        run(s=s)


@pytest.mark.parametrize("field,value", [
    ("sequence", True), ("sequence", 2001), ("kind", "LIVE_SEND"), ("kind", []),
    ("occurred_at_ms", 99), ("received_at_ms", 1001), ("contracts", -1),
    ("contracts", True), ("event_id", "bad event"), ("provider", "Other"),
    ("receipt_sha256", "INVALID"), ("broker_order_id", "bad id"),
])
def test_invalid_event_rejected(field, value):
    events, manifest = make_events()
    events[0][field] = value
    with pytest.raises(ValueError):
        run(events=events, manifest=manifest)


def test_late_out_of_order_receipt_is_quarantined():
    specs = [("SUBMITTED", 100, 0, None), ("ACCEPTED", 130, 0, "b"),
             ("FILL", 120, 1, "b")]
    events, manifest = make_events(specs=specs)
    with pytest.raises(ValueError, match="out-of-order"):
        run(events=events, manifest=manifest)


def test_malformed_manifest_and_empty_events_fail():
    events, manifest = make_events()
    with pytest.raises(ValueError):
        run(events=[], manifest=manifest)
    for field, value in (("expected_event_count", True), ("expected_event_count", 0),
                         ("expected_head_sha256", "invalid"), ("manifest_recorded_at_ms", 1001)):
        m = {**manifest, field: value}
        with pytest.raises(ValueError):
            run(events=events, manifest=m)
    with pytest.raises(ValueError):
        run(events=events, manifest={**manifest, "extra": 1})
    with pytest.raises(ValueError, match="predates"):
        run(events=events, manifest={**manifest, "manifest_recorded_at_ms": 140})


def test_oversized_population_rejected_before_replay():
    events, manifest = make_events()
    with pytest.raises(ValueError, match="unbounded"):
        run(events=events * 668, manifest=manifest)


def test_randomized_partition_fills_preserve_quantities():
    rng = random.Random(20261026)
    for _ in range(250):
        s = scope()
        s["requested_contracts"] = rng.randint(1, 100)
        remaining = s["requested_contracts"]
        specs = [("SUBMITTED", 100, 0, None), ("ACCEPTED", 110, 0, "b")]
        t = 120
        while remaining:
            take = rng.randint(1, remaining)
            specs.append(("FILL", t, take, "b"))
            remaining -= take
            t += 10
        s["as_of_ms"] = max(1000, t + 10)
        events, manifest = make_events(s=s, specs=specs)
        x = run(s=s, events=events, manifest=manifest)
        assert x["declared_filled_contracts"] == s["requested_contracts"]
        assert x["declared_remaining_contracts"] == 0
        assert x["status"] == "DECLARED_FULL_FILL_UNVERIFIED"
