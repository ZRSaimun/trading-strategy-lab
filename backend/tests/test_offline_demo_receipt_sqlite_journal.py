"""Offline SQLite journal regressions using synthetic, unauthenticated receipts."""
import copy
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.offline_demo_order_receipt_replay import fingerprint_demo_order_event
from app.offline_demo_receipt_sqlite_journal import (
    append_declared_demo_receipt_snapshot as append,
    read_declared_demo_receipt_journal_head as read,
)

ZERO = "0" * 64
IDENTITY = ("provider", "venue", "account_alias", "instrument", "client_order_id")


def scope(as_of=200, requested=5, order="test-order"):
    return dict(provider="Synthetic", venue="DEMO", account_alias="account-1",
                instrument="XAUUSD-CFD", client_order_id=order, side="BUY",
                requested_contracts=requested, submitted_at_ms=100,
                as_of_ms=as_of, intent_sha256="a" * 64)


def history(s, specs):
    events = []
    previous = ZERO
    for n, (kind, occurred, received, contracts, broker) in enumerate(specs, 1):
        event = dict(sequence=n, event_id=f"event-{n}", kind=kind,
                     occurred_at_ms=occurred, received_at_ms=received,
                     broker_order_id=broker, contracts=contracts,
                     receipt_sha256=f"{n:064x}", previous_event_sha256=previous,
                     **{key: s[key] for key in IDENTITY})
        events.append(event)
        previous = fingerprint_demo_order_event(s, event)
    manifest = dict(expected_event_count=len(events),
                    expected_head_sha256=previous,
                    manifest_recorded_at_ms=max(e["received_at_ms"] for e in events))
    return events, manifest


def initial():
    s = scope()
    events, manifest = history(s, [
        ("SUBMITTED", 100, 101, 0, None),
        ("ACCEPTED", 110, 111, 0, "broker-1"),
        ("FILL", 120, 121, 2, "broker-1")])
    return s, events, manifest


def next_snapshot(*, fill=1, at=220, requested=5):
    s = scope(as_of=400, requested=requested)
    events, manifest = history(s, [
        ("SUBMITTED", 100, 101, 0, None),
        ("ACCEPTED", 110, 111, 0, "broker-1"),
        ("FILL", 120, 121, 2, "broker-1"),
        ("FILL", at, at + 1, fill, "broker-1")])
    return s, events, manifest


def test_commit_restart_read_only_and_no_execution(tmp_path):
    path = tmp_path / "declared.sqlite"
    s, events, manifest = initial()
    first = append(path, s, events, manifest, ZERO)
    assert first["revision"] == 1
    assert first["declared_filled_contracts"] == 2
    assert first["declared_remaining_contracts"] == 3
    assert first["local_chain_consistent"]
    assert not first["broker_receipts_authenticated"]
    assert not first["broker_population_complete"]
    assert not first["may_execute_demo_order"]
    assert not first["may_execute_real_order"]
    assert read(path, s)["checkpoint_sha256"] == first["checkpoint_sha256"]
    new = next_snapshot()
    second = append(path, *new, first["checkpoint_sha256"])
    assert second["revision"] == 2
    assert second["previous_checkpoint_sha256"] == first["checkpoint_sha256"]
    assert second["declared_filled_contracts"] == 3
    assert second["declared_remaining_contracts"] == 2
    assert read(path, s)["checkpoint_sha256"] == second["checkpoint_sha256"]
    assert read(path, new[0]) == read(path, s)


def test_idempotent_exact_retry_does_not_add_revision(tmp_path):
    path = tmp_path / "journal.sqlite"
    args = initial()
    first = append(path, *args, ZERO)
    again = append(path, *copy.deepcopy(args), ZERO)
    assert again["status"] == "IDEMPOTENT_DECLARED_RETRY"
    assert again["checkpoint_sha256"] == first["checkpoint_sha256"]
    assert read(path, args[0])["revision"] == 1


def test_stale_cas_rejected_without_mutation(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = append(path, *initial(), ZERO)
    with pytest.raises(ValueError, match="compare-and-swap"):
        append(path, *next_snapshot(), ZERO)
    assert read(path, initial()[0])["checkpoint_sha256"] == first["checkpoint_sha256"]


def test_rewritten_history_even_rehashed_fails_closed(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = append(path, *initial(), ZERO)
    s, _, _ = next_snapshot()
    changed_events, changed_manifest = history(s, [
        ("SUBMITTED", 100, 101, 0, None),
        ("ACCEPTED", 110, 111, 0, "broker-1"),
        ("FILL", 120, 121, 1, "broker-1"),
        ("FILL", 220, 221, 2, "broker-1")])
    with pytest.raises(ValueError, match="prefix changed"):
        append(path, s, changed_events, changed_manifest, first["checkpoint_sha256"])
    assert read(path, initial()[0])["revision"] == 1


def test_pre_cutoff_backfill_fails_closed(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = append(path, *initial(), ZERO)
    s, events, manifest = next_snapshot(at=150)
    with pytest.raises(ValueError, match="pre-cutoff"):
        append(path, s, events, manifest, first["checkpoint_sha256"])
    assert read(path, s)["revision"] == 1


def test_invalid_receipt_rolls_back_and_preserves_head(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = append(path, *initial(), ZERO)
    s, events, manifest = next_snapshot()
    events[-1]["contracts"] = 100
    with pytest.raises(ValueError):
        append(path, s, events, manifest, first["checkpoint_sha256"])
    assert read(path, s)["checkpoint_sha256"] == first["checkpoint_sha256"]


@pytest.mark.parametrize("mutation", ["payload", "head", "gap", "previous"])
def test_persisted_corruption_rejected_on_read_and_append(tmp_path, mutation):
    path = tmp_path / "journal.sqlite"
    first = append(path, *initial(), ZERO)
    with sqlite3.connect(path) as conn:
        if mutation == "payload":
            conn.execute(
                "UPDATE demo_order_snapshots SET payload_json=replace(payload_json, 'account-1', 'account-2')")
        elif mutation == "head":
            conn.execute("UPDATE demo_order_journal SET head_sha256=?", ("f" * 64,))
        elif mutation == "gap":
            conn.execute("UPDATE demo_order_snapshots SET revision=3")
        else:
            conn.execute("UPDATE demo_order_snapshots SET previous_sha256=?", ("f" * 64,))
    with pytest.raises(ValueError):
        read(path, initial()[0])
    with pytest.raises(ValueError):
        append(path, *next_snapshot(), first["checkpoint_sha256"])


def test_separate_order_identities_and_invalid_genesis(tmp_path):
    path = tmp_path / "journal.sqlite"
    s, events, manifest = initial()
    with pytest.raises(ValueError, match="genesis"):
        append(path, s, events, manifest, "a" * 64)
    one = append(path, s, events, manifest, ZERO)
    other = scope(order="other")
    other_events, other_manifest = history(other, [
        ("SUBMITTED", 100, 101, 0, None),
        ("ACCEPTED", 110, 111, 0, "broker-1")])
    two = append(path, other, other_events, other_manifest, ZERO)
    assert one["checkpoint_sha256"] != two["checkpoint_sha256"]
    assert read(path, s)["revision"] == 1
    assert read(path, other)["revision"] == 1


def test_concurrent_writers_with_same_cas_only_one_commits(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = append(path, *initial(), ZERO)
    a = next_snapshot(fill=1)
    b = next_snapshot(fill=2)
    def writer(payload):
        try:
            return append(path, *payload, first["checkpoint_sha256"])
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (a, b)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert any("compare-and-swap" in result for result in results if isinstance(result, str))
    assert read(path, initial()[0])["revision"] == 2


def test_seeded_many_order_restarts_preserve_exposure(tmp_path):
    path = tmp_path / "journal.sqlite"
    rng = random.Random(20261026)
    for n in range(25):
        qty = rng.randint(3, 30)
        first_qty = rng.randint(1, 2)
        second_qty = rng.randint(1, qty - first_qty)
        s = scope(requested=qty, order=f"order-{n}")
        events, manifest = history(s, [
            ("SUBMITTED", 100, 101, 0, None),
            ("ACCEPTED", 110, 111, 0, "broker-1"),
            ("FILL", 120, 121, first_qty, "broker-1")])
        one = append(path, s, events, manifest, ZERO)
        later = scope(as_of=400, requested=qty, order=f"order-{n}")
        later_events, later_manifest = history(later, [
            ("SUBMITTED", 100, 101, 0, None),
            ("ACCEPTED", 110, 111, 0, "broker-1"),
            ("FILL", 120, 121, first_qty, "broker-1"),
            ("FILL", 220, 221, second_qty, "broker-1")])
        append(path, later, later_events, later_manifest, one["checkpoint_sha256"])
        head = read(path, s)
        assert head["declared_filled_contracts"] == first_qty + second_qty
        assert head["declared_remaining_contracts"] == qty - first_qty - second_qty
        assert head["revision"] == 2


@pytest.mark.parametrize("invalid", [None, "", ":memory:", 42])
def test_requires_file_path(tmp_path, invalid):
    with pytest.raises(ValueError):
        append(invalid, *initial(), ZERO)


def test_read_does_not_create_missing_file(tmp_path):
    path = tmp_path / "not-created.sqlite"
    with pytest.raises(ValueError, match="No existing"):
        read(path, initial()[0])
    assert not path.exists()


def test_rejects_boolean_or_non_sha_cas(tmp_path):
    for expected in (True, None, "X" * 64, "0" * 63):
        with pytest.raises(ValueError, match="checkpoint SHA"):
            append(tmp_path / "journal.sqlite", *initial(), expected)
