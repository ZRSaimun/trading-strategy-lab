"""Offline, declared-only as-of economic release rescheduling census.

No authenticated vendor custody, complete calendar, market data or trade clearance.
"""
from __future__ import annotations

import hashlib
import json
from app.offline_event_asof_guard import _utc, audit_declared_event_asof


def audit_declared_schedule_drift_asof(
    revisions, *, decision_utc, source_id, material_drift_minutes=30
):
    """Measure visible pre-release schedule drift, not market predictability.

    Distinguishes a consensus-only revision from a changed release time.
    Every future revision is validated by the upstream fail-closed guard, but
    only receipts strictly before the decision minute enter this census.
    """
    if type(material_drift_minutes) is not int or not 0 <= material_drift_minutes <= 1440:
        raise ValueError("material_drift_minutes must be integer 0..1440")
    snapshot = audit_declared_event_asof(
        revisions, decision_utc=decision_utc, source_id=source_id
    )
    cutoff = _utc(decision_utc)
    schedules = {}
    for entry in revisions:
        if entry["kind"] == "schedule" and _utc(entry["observed_utc"]) < cutoff:
            schedules.setdefault(entry["event_id"], []).append(entry)

    observations = []
    for event in snapshot["events"]:
        history = sorted(schedules[event["event_id"]], key=lambda x: x["revision"])
        initial = _utc(history[0]["scheduled_utc"])
        previous = initial
        change_count = 0
        forecast_only_count = 0
        total_abs_shift = 0
        max_abs_shift = 0
        last_change_receipt = None
        for entry in history[1:]:
            scheduled = _utc(entry["scheduled_utc"])
            shift = int((scheduled - previous).total_seconds() // 60)
            if shift:
                change_count += 1
                total_abs_shift += abs(shift)
                max_abs_shift = max(max_abs_shift, abs(shift))
                last_change_receipt = _utc(entry["observed_utc"])
            else:
                forecast_only_count += 1
            previous = scheduled
        net = int((previous - initial).total_seconds() // 60)
        age_anchor = min(cutoff, previous)
        last_age = (
            int((age_anchor - last_change_receipt).total_seconds() // 60)
            if last_change_receipt is not None else None
        )
        observations.append({
            "event_id": event["event_id"],
            "initial_scheduled_utc": initial.isoformat(),
            "latest_scheduled_utc": previous.isoformat(),
            "visible_schedule_revision_count": len(history),
            "changed_schedule_count": change_count,
            "unchanged_schedule_revision_count": forecast_only_count,
            "net_schedule_drift_minutes": net,
            "total_absolute_schedule_drift_minutes": total_abs_shift,
            "largest_single_schedule_shift_minutes": max_abs_shift,
            "last_changed_schedule_observed_utc": (
                last_change_receipt.isoformat() if last_change_receipt else None
            ),
            "age_anchor_utc": age_anchor.isoformat(),
            "minutes_since_last_schedule_change": last_age,
            "exceeds_declared_material_drift": (
                total_abs_shift > material_drift_minutes if change_count else False
            ),
            "status": (
                "NO_VISIBLE_SCHEDULE_CHANGE" if not change_count
                else "DECLARED_MATERIAL_SCHEDULE_DRIFT"
                if total_abs_shift > material_drift_minutes
                else "DECLARED_NONMATERIAL_SCHEDULE_DRIFT"
            ),
        })
    envelope = {
        "schema_version": 1,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "material_drift_minutes": material_drift_minutes,
        "observations": observations,
    }
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {
        "research_only": True,
        "trade_authorized": False,
        "authenticated_calendar": False,
        "coverage_verified": False,
        "receipt_provenance_verified": False,
        "source_id": snapshot["source_id"],
        "decision_utc": snapshot["decision_utc"],
        "visible_event_count": snapshot["visible_event_count"],
        "changed_schedule_event_count": sum(
            x["changed_schedule_count"] > 0 for x in observations
        ),
        "material_schedule_drift_event_count": sum(
            x["exceeds_declared_material_drift"] for x in observations
        ),
        "material_drift_minutes": material_drift_minutes,
        "observations": observations,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "schedule_drift_audit_schema_version": 1,
        "schedule_drift_audit_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }
