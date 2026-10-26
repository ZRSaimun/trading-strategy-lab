"""Synthetic tests for read-only off-journal checkpoint comparison."""
import copy
import sqlite3

import pytest

from app.offline_demo_order_receipt_replay import fingerprint_demo_order_event
from app.offline_demo_receipt_sqlite_journal import (
    append_declared_demo_receipt_snapshot as append,
    read_declared_demo_receipt_journal_head as read,
)
from app.offline_demo_receipt_anchor_audit import (
    audit_declared_demo_receipt_anchor_evidence as audit,
)

ZERO = "0" * 64
IDENTITY = ("provider", "venue", "account_alias", "instrument", "client_order_id")


def payload(as_of=200, fills=(2,), order="order-1"):
    s = dict(provider="Synthetic", venue="DEMO", account_alias="account-1",
             instrument="XAUUSD-CFD", client_order_id=order, side="BUY",
             requested_contracts=5, submitted_at_ms=100,
             as_of_ms=as_of, intent_sha256="a" * 64)
    specs = [("SUBMITTED", 100, 101, 0, None),
             ("ACCEPTED", 110, 111, 0, "broker-1")]
    for i, fill in enumerate(fills):
        specs.append(("FILL", 120 + 100 * i, 121 + 100 * i, fill, "broker-1"))
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
    return s, events, manifest


def anchor(report, *, as_of=200, witnessed=250, ref="vault/checkpoint-1"):
    return dict(revision=report["revision"],
                checkpoint_sha256=report["checkpoint_sha256"],
                previous_checkpoint_sha256=report["previous_checkpoint_sha256"],
                as_of_ms=as_of, witnessed_at_ms=witnessed,
                witness_id="offline-vault", evidence_ref=ref)


def seed(tmp_path):
    path = tmp_path / "demo.sqlite"
    s, events, manifest = payload()
    first = append(path, s, events, manifest, ZERO)
    return path, s, first


def extend(path, first):
    later = payload(as_of=400, fills=(2, 1))
    second = append(path, *later, first["checkpoint_sha256"])
    return later[0], second


def test_matching_declared_anchor_is_not_authentication(tmp_path):
    path, s, first = seed(tmp_path)
    result = audit(path, s, [anchor(first)], 300)
    assert result["status"] == "DECLARED_HEAD_ANCHOR_MATCH_ONLY"
    assert result["head_has_matching_declared_anchor"]
    assert result["declared_anchor_count"] == 1
    assert not result["external_witness_authenticated"]
    assert not result["independent_custody_verified"]
    assert not result["broker_population_complete"]
    assert not result["may_execute_demo_order"]
    assert not result["may_execute_real_order"]
    assert read(path, s)["checkpoint_sha256"] == first["checkpoint_sha256"]


def test_new_head_without_new_anchor_holds(tmp_path):
    path, s, first = seed(tmp_path)
    later_scope, second = extend(path, first)
    result = audit(path, s, [anchor(first)], 500)
    assert result["status"] == "HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED"
    assert result["local_head_revision"] == 2
    assert not result["head_has_matching_declared_anchor"]
    both = audit(path, later_scope, [anchor(first), anchor(
        second, as_of=400, witnessed=450, ref="vault/checkpoint-2")], 500)
    assert both["status"] == "DECLARED_HEAD_ANCHOR_MATCH_ONLY"
    assert both["declared_anchor_count"] == 2


@pytest.mark.parametrize("field,value", [
    ("checkpoint_sha256", "f" * 64),
    ("previous_checkpoint_sha256", "f" * 64),
    ("checkpoint_sha256", "X" * 64),
    ("as_of_ms", 199),
    ("witnessed_at_ms", 199),
    ("witnessed_at_ms", 999),
    ("revision", 2),
    ("revision", True),
    ("evidence_ref", ""),
    ("witness_id", "../../bad"),
])
def test_invalid_or_unavailable_anchor_fails_closed(tmp_path, field, value):
    path, s, first = seed(tmp_path)
    bad = anchor(first)
    bad[field] = value
    with pytest.raises(ValueError):
        audit(path, s, [bad], 500)


def test_duplicate_or_nonascending_revision_rejected(tmp_path):
    path, s, first = seed(tmp_path)
    a = anchor(first)
    b = anchor(first, ref="vault/checkpoint-2")
    with pytest.raises(ValueError, match="nonascending"):
        audit(path, s, [a, b], 500)


def test_duplicate_evidence_reference_rejected(tmp_path):
    path, s, first = seed(tmp_path)
    _, second = extend(path, first)
    with pytest.raises(ValueError, match="reused"):
        audit(path, s, [anchor(first), anchor(second, as_of=400, witnessed=450)], 500)


def test_future_and_reversed_witness_chronology_rejected(tmp_path):
    path, s, first = seed(tmp_path)
    _, second = extend(path, first)
    with pytest.raises(ValueError, match="chronology"):
        audit(path, s, [anchor(first, witnessed=470),
                        anchor(second, as_of=400, witnessed=450,
                               ref="vault/checkpoint-2")], 500)


def test_corrupted_local_journal_fails_closed(tmp_path):
    path, s, first = seed(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE demo_order_journal SET head_sha256=?", ("f" * 64,))
    with pytest.raises(ValueError):
        audit(path, s, [anchor(first)], 500)


def test_wrong_order_identity_cannot_reuse_anchor(tmp_path):
    path, s, first = seed(tmp_path)
    wrong = copy.deepcopy(s)
    wrong["client_order_id"] = "another-order"
    with pytest.raises(ValueError, match="No matching"):
        audit(path, wrong, [anchor(first)], 500)


@pytest.mark.parametrize("bad", [[], {}, None, [None], ["invalid"],
                                  [dict(revision=1)], ["a"] * 33])
def test_unbounded_or_malformed_anchor_population_rejected(tmp_path, bad):
    path, s, _ = seed(tmp_path)
    with pytest.raises(ValueError):
        audit(path, s, bad, 500)


def test_bad_evaluation_cutoff_rejected(tmp_path):
    path, s, first = seed(tmp_path)
    for bad in (True, None, 0, -1, "500"):
        with pytest.raises(ValueError, match="cutoff"):
            audit(path, s, [anchor(first)], bad)
