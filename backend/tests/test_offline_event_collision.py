"""Synthetic as-of event-window collision regressions (no trading)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.offline_event_collision import audit_declared_event_collision_asof


def row(event_id="A", minute=0, *, revision=1,
        observed="2026-10-28T12:00:00Z", kind="schedule", actual=None):
    scheduled = datetime(2026, 10, 28, 18, tzinfo=timezone.utc) + timedelta(minutes=minute)
    return {"event_id": event_id, "revision": revision, "kind": kind,
            "scheduled_utc": scheduled.isoformat(),
            "published_utc": observed, "observed_utc": observed,
            "forecast": "3", "actual": actual}


def audit(rows, decision="2026-10-28T18:00:00Z", before=15, after=15,
          source="synthetic-calendar"):
    return audit_declared_event_collision_asof(
        rows, decision_utc=decision, source_id=source,
        before_minutes=before, after_minutes=after,
    )


def test_empty_inventory_not_trade_clearance():
    x = audit([])
    assert x["status"] == "NO_DECLARED_WINDOW_AT_DECISION"
    assert x["direct_event_count"] == 0
    assert x["relevant_clusters"] == []
    assert not x["trade_authorized"] and not x["coverage_verified"]
    assert not x["single_event_attribution_verified"]


def test_isolated_event_is_not_proven_causation():
    x = audit([row()])
    assert x["status"] == "ISOLATED_DECLARED_WINDOW"
    assert x["direct_event_ids"] == ["A"]
    assert x["relevant_clusters"][0]["event_ids"] == ["A"]
    assert not x["single_event_attribution_verified"]


def test_neighbor_outside_decision_still_ambiguous_on_touching_boundary():
    # A: [17:45,18:15], B: [18:15,18:45]. B is not active at 18:00.
    x = audit([row("A"), row("B", 30)])
    assert x["direct_event_ids"] == ["A"]
    assert x["status"] == "OVERLAPPING_DECLARED_WINDOWS"
    assert x["relevant_clusters"][0]["event_ids"] == ["A", "B"]
    assert x["relevant_clusters"][0]["decision_window_event_ids"] == ["A"]


def test_transitive_overlap_includes_nonadjacent_neighbor():
    x = audit([row("A"), row("B", 25), row("C", 50)])
    assert x["direct_event_ids"] == ["A"]
    assert x["relevant_clusters"][0]["event_ids"] == ["A", "B", "C"]


def test_gap_of_one_minute_does_not_collide():
    x = audit([row("A"), row("B", 31)])
    assert x["status"] == "ISOLATED_DECLARED_WINDOW"
    assert x["relevant_clusters"][0]["event_ids"] == ["A"]


def test_decision_at_inclusive_edge_and_zero_width():
    x = audit([row()], decision="2026-10-28T18:15:00Z")
    assert x["direct_event_ids"] == ["A"]
    assert audit([row()], before=0, after=0)["direct_event_ids"] == ["A"]
    assert audit([row()], decision="2026-10-28T18:01:00Z",
                 before=0, after=0)["direct_event_ids"] == []


def test_invisible_future_schedule_cannot_create_collision():
    rows = [row("A"), row("B", 30, observed="2026-10-28T18:00:00Z")]
    x = audit(rows)
    assert x == audit(rows[:1])
    y = audit(rows, decision="2026-10-28T18:01:00Z")
    assert y["status"] == "OVERLAPPING_DECLARED_WINDOWS"


def test_reschedule_visible_only_after_strict_cutoff():
    rows = [row("A"), row("B", 60)]
    changed = row("B", 30, revision=2, observed="2026-10-28T17:59:00Z")
    rows.append(changed)
    assert audit(rows, decision="2026-10-28T17:59:00Z")["status"] == "ISOLATED_DECLARED_WINDOW"
    assert audit(rows, decision="2026-10-28T18:00:00Z")["status"] == "OVERLAPPING_DECLARED_WINDOWS"


def test_source_cutoff_policy_order_and_future_invariance():
    rows = [row("A"), row("B", 30)]
    original = deepcopy(rows)
    x = audit(rows)
    assert x == audit(list(reversed(rows)))
    assert rows == original
    assert audit(rows, source="other")["event_collision_audit_sha256"] != x["event_collision_audit_sha256"]
    assert audit(rows, before=14)["event_collision_audit_sha256"] != x["event_collision_audit_sha256"]
    assert audit(rows, decision="2026-10-28T18:01:00Z")["event_collision_audit_sha256"] != x["event_collision_audit_sha256"]
    assert audit(rows + [row("C", 90, observed="2026-10-28T18:00:00Z")]) == x


def test_digest_independent_reconstruction():
    x = audit([row("A"), row("B", 30)])
    envelope = {"schema_version": 1,
                "research_envelope_v2_sha256": x["research_envelope_v2_sha256"],
                "before_minutes": x["before_minutes"],
                "after_minutes": x["after_minutes"],
                "direct_event_ids": x["direct_event_ids"],
                "relevant_clusters": x["relevant_clusters"],
                "status": x["status"]}
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert x["event_collision_audit_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()


@pytest.mark.parametrize("bad", [-1, 1441, True, 1.2, "15", None])
def test_invalid_policy_fails_closed(bad):
    with pytest.raises(ValueError, match="before_minutes"):
        audit([row()], before=bad)
    with pytest.raises(ValueError, match="after_minutes"):
        audit([row()], after=bad)


def test_invalid_revision_still_rejected_even_if_future():
    invalid = row("B", 60, observed="2026-10-28T18:00:00Z")
    invalid["actual"] = "2"
    with pytest.raises(ValueError):
        audit([row(), invalid])
