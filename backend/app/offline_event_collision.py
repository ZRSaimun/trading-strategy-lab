"""Offline, source-local as-of economic event-window overlap research.

Declared schedules are not authenticated; no market or trade clearance.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json

from app.offline_event_asof_guard import _utc, audit_declared_event_asof


def audit_declared_event_collision_asof(
    revisions, *, decision_utc, source_id, before_minutes=30, after_minutes=15
):
    """Cluster *all* visible event windows before attributing a decision.

    Connected components include adjacent windows that touch at a boundary.
    A decision can be inside only one event's interval yet remain ambiguous
    because that interval overlaps a different event's interval. Components
    are conservative and do not prove economic causation or calendar coverage.
    """
    for name, value in (("before_minutes", before_minutes),
                        ("after_minutes", after_minutes)):
        if type(value) is not int or not 0 <= value <= 1440:
            raise ValueError(f"{name} must be an integer from 0 to 1440")
    snapshot = audit_declared_event_asof(
        revisions, decision_utc=decision_utc, source_id=source_id
    )
    cutoff = _utc(decision_utc)
    intervals = []
    for event in snapshot["events"]:
        scheduled = _utc(event["scheduled_utc"])
        start = scheduled - timedelta(minutes=before_minutes)
        end = scheduled + timedelta(minutes=after_minutes)
        intervals.append({
            "event_id": event["event_id"],
            "scheduled_utc": event["scheduled_utc"],
            "window_start_utc": start.isoformat(),
            "window_end_utc": end.isoformat(),
            "decision_inside_window": start <= cutoff <= end,
        })
    intervals.sort(key=lambda x: (x["window_start_utc"], x["event_id"]))

    # Sweep in O(n log n) instead of quadratic pair enumeration. A chain of
    # overlapping windows forms one cluster even if its endpoints do not touch.
    groups = []
    for item in intervals:
        start = _utc(item["window_start_utc"])
        end = _utc(item["window_end_utc"])
        if groups and start <= groups[-1]["_max_end"]:
            group = groups[-1]
            group["events"].append(item)
            if end > group["_max_end"]:
                group["_max_end"] = end
        else:
            groups.append({"events": [item], "_max_end": end})

    # Only report components relevant to this decision; retain overlapping
    # off-decision neighbors so single-event attribution cannot be fabricated.
    relevant = []
    for group in groups:
        events = group["events"]
        if not any(item["decision_inside_window"] for item in events):
            continue
        relevant.append({
            "event_ids": sorted(item["event_id"] for item in events),
            "event_count": len(events),
            "decision_window_event_ids": sorted(
                item["event_id"] for item in events
                if item["decision_inside_window"]
            ),
            "cluster_start_utc": min(item["window_start_utc"] for item in events),
            "cluster_end_utc": max(item["window_end_utc"] for item in events),
            "events": sorted(events, key=lambda x: x["event_id"]),
        })
    direct_ids = sorted(item["event_id"] for item in intervals
                        if item["decision_inside_window"])
    ambiguous = any(group["event_count"] > 1 for group in relevant)
    status = (
        "NO_DECLARED_WINDOW_AT_DECISION" if not direct_ids else
        "OVERLAPPING_DECLARED_WINDOWS" if ambiguous else
        "ISOLATED_DECLARED_WINDOW"
    )
    envelope = {
        "schema_version": 1,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "before_minutes": before_minutes,
        "after_minutes": after_minutes,
        "direct_event_ids": direct_ids,
        "relevant_clusters": relevant,
        "status": status,
    }
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return {
        "research_only": True,
        "trade_authorized": False,
        "authenticated_calendar": False,
        "coverage_verified": False,
        "receipt_provenance_verified": False,
        "single_event_attribution_verified": False,
        "source_id": snapshot["source_id"],
        "decision_utc": snapshot["decision_utc"],
        "visible_event_count": snapshot["visible_event_count"],
        "before_minutes": before_minutes,
        "after_minutes": after_minutes,
        "direct_event_ids": direct_ids,
        "direct_event_count": len(direct_ids),
        "relevant_clusters": relevant,
        "ambiguous_declared_overlap": ambiguous,
        "status": status,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "event_collision_audit_schema_version": 1,
        "event_collision_audit_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }
