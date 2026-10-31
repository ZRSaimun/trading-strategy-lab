"""Offline, fail-closed as-of macro-news candidate cohort census.

A declared calendar is neither complete nor authenticated. This diagnostic
never authorizes trade entry, event attribution, or historical P&L inclusion.
"""
from __future__ import annotations

import hashlib
import json

from app.offline_event_asof_guard import _utc
from app.offline_event_collision import audit_declared_event_collision_asof

_MAX_CANDIDATES = 256


def audit_declared_news_candidate_census(
    revisions, *, decision_utcs, source_id, before_minutes=30, after_minutes=15
):
    """Classify a frozen chronological cohort under each decision's own as-of view.

    Historical decisions must be strictly increasing, UTC-minute aligned and
    independently audited. A later calendar revision must not rewrite an
    earlier candidate. No status means an event is causally attributable.
    """
    if not isinstance(decision_utcs, (list, tuple)) or not 1 <= len(decision_utcs) <= _MAX_CANDIDATES:
        raise ValueError("Bounded nonempty candidate decision sequence required")
    previous = None
    canonical_decisions = []
    for raw in decision_utcs:
        dt = _utc(raw)
        if previous is not None and dt <= previous:
            raise ValueError("Candidate decisions must increase strictly")
        previous = dt
        canonical_decisions.append(dt.isoformat())

    records = []
    for decision in canonical_decisions:
        audit = audit_declared_event_collision_asof(
            revisions, decision_utc=decision, source_id=source_id,
            before_minutes=before_minutes, after_minutes=after_minutes,
        )
        if audit["status"] == "OVERLAPPING_DECLARED_WINDOWS":
            reason = "CONFOUNDED_DECLARED_WINDOWS"
        elif audit["status"] == "ISOLATED_DECLARED_WINDOW":
            reason = "DECLARED_SINGLE_WINDOW_UNVERIFIED"
        elif audit["status"] == "NO_DECLARED_WINDOW_AT_DECISION":
            reason = "NO_DECLARED_WINDOW_UNVERIFIED"
        else:
            raise ValueError("Unexpected event collision status")
        records.append({
            "decision_utc": decision,
            "declared_window_event_ids": audit["direct_event_ids"],
            "declared_cluster_event_ids": [
                group["event_ids"] for group in audit["relevant_clusters"]
            ],
            "attribution_exclusion_reason": reason,
            "event_collision_audit_sha256": audit["event_collision_audit_sha256"],
            "research_envelope_v2_sha256": audit["research_envelope_v2_sha256"],
            "eligible_for_event_attribution": False,
            "trade_authorized": False,
        })
    envelope = {
        "schema_version": 1,
        "source_id": source_id,
        "before_minutes": before_minutes,
        "after_minutes": after_minutes,
        "candidate_decision_utcs": canonical_decisions,
        "records": records,
    }
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "research_only": True,
        "trade_authorized": False,
        "authenticated_calendar": False,
        "coverage_verified": False,
        "receipt_provenance_verified": False,
        "event_attribution_verified": False,
        "source_id": source_id,
        "before_minutes": before_minutes,
        "after_minutes": after_minutes,
        "candidate_count": len(records),
        "confounded_declared_count": sum(
            r["attribution_exclusion_reason"] == "CONFOUNDED_DECLARED_WINDOWS"
            for r in records
        ),
        "unverified_isolated_count": sum(
            r["attribution_exclusion_reason"] == "DECLARED_SINGLE_WINDOW_UNVERIFIED"
            for r in records
        ),
        "unverified_no_window_count": sum(
            r["attribution_exclusion_reason"] == "NO_DECLARED_WINDOW_UNVERIFIED"
            for r in records
        ),
        "records": records,
        "candidate_census_schema_version": 1,
        "candidate_census_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
