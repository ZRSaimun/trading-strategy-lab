"""Synthetic, offline causal schedule drift regressions."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.offline_event_schedule_drift import audit_declared_schedule_drift_asof


def row(revision=1, *, event_id="A", scheduled="2026-10-28T18:00:00Z",
        observed="2026-10-28T12:00:00Z", forecast="3.0", kind="schedule",
        actual=None, published=None):
    return {
        "event_id": event_id, "revision": revision, "kind": kind,
        "scheduled_utc": scheduled,
        "published_utc": published or observed,
        "observed_utc": observed,
        "forecast": forecast, "actual": actual,
    }


def audit(rows, decision="2026-10-28T17:00:00Z",
          source="synthetic-calendar", material=30):
    return audit_declared_schedule_drift_asof(
        rows, decision_utc=decision, source_id=source,
        material_drift_minutes=material,
    )


def shifted_rows():
    return [
        row(),
        row(2, scheduled="2026-10-28T18:40:00Z",
            observed="2026-10-28T13:00:00Z"),
        row(3, scheduled="2026-10-28T18:10:00Z",
            observed="2026-10-28T14:00:00Z"),
    ]


def test_empty_inventory_never_grants_trade_clearance():
    report = audit([])
    assert report["visible_event_count"] == 0
    assert report["changed_schedule_event_count"] == 0
    assert report["coverage_verified"] is False
    assert report["authenticated_calendar"] is False
    assert report["trade_authorized"] is False


def test_forecast_only_revision_is_not_reschedule():
    rows = [row(), row(2, observed="2026-10-28T13:00:00Z", forecast="3.1")]
    x = audit(rows)["observations"][0]
    assert x["changed_schedule_count"] == 0
    assert x["unchanged_schedule_revision_count"] == 1
    assert x["net_schedule_drift_minutes"] == 0
    assert x["minutes_since_last_schedule_change"] is None


def test_reversion_retains_absolute_drift_not_just_net():
    x = audit(shifted_rows())["observations"][0]
    assert x["changed_schedule_count"] == 2
    assert x["net_schedule_drift_minutes"] == 10
    assert x["total_absolute_schedule_drift_minutes"] == 70
    assert x["largest_single_schedule_shift_minutes"] == 40
    assert x["status"] == "DECLARED_MATERIAL_SCHEDULE_DRIFT"
    assert x["minutes_since_last_schedule_change"] == 180


def test_strict_receipt_cutoff_and_future_invariance():
    rows = shifted_rows()
    at = audit(rows, decision="2026-10-28T13:00:00Z")
    before = audit(rows[:1], decision="2026-10-28T13:00:00Z")
    assert at == before
    after = audit(rows, decision="2026-10-28T13:01:00Z")
    assert after["observations"][0]["changed_schedule_count"] == 1


def test_threshold_inclusive_and_zero():
    rows = shifted_rows()[:2]
    assert audit(rows, material=40)["material_schedule_drift_event_count"] == 0
    assert audit(rows, material=39)["material_schedule_drift_event_count"] == 1
    assert audit(rows, material=0)["material_schedule_drift_event_count"] == 1


def test_after_release_age_is_anchored_to_event_not_future_decision():
    rows = shifted_rows() + [
        row(4, kind="result", scheduled="2026-10-28T18:10:00Z",
            observed="2026-10-28T18:11:00Z",
            published="2026-10-28T18:10:00Z", actual="3.2")
    ]
    x = audit(rows, decision="2026-10-28T18:12:00Z")["observations"][0]
    y = audit(rows, decision="2026-10-28T19:00:00Z")["observations"][0]
    assert x["minutes_since_last_schedule_change"] == 250
    assert y["minutes_since_last_schedule_change"] == 250


def test_order_independent_source_cutoff_policy_bound_and_no_mutation():
    rows = shifted_rows()
    original = deepcopy(rows)
    a = audit(rows)
    assert audit(list(reversed(rows))) == a
    assert rows == original
    assert audit(rows, source="another")["schedule_drift_audit_sha256"] != a[
        "schedule_drift_audit_sha256"
    ]
    assert audit(rows, decision="2026-10-28T17:01:00Z")[
        "schedule_drift_audit_sha256"
    ] != a["schedule_drift_audit_sha256"]
    assert audit(rows, material=0)["schedule_drift_audit_sha256"] != a[
        "schedule_drift_audit_sha256"
    ]


def test_digest_can_be_independently_reconstructed():
    report = audit(shifted_rows())
    payload = {
        "schema_version": 1,
        "research_envelope_v2_sha256": report["research_envelope_v2_sha256"],
        "material_drift_minutes": report["material_drift_minutes"],
        "observations": report["observations"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    assert report["schedule_drift_audit_sha256"] == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("material", [-1, 1441, True, 1.5, "30", None])
def test_invalid_policy_fails_closed(material):
    with pytest.raises(ValueError, match="material_drift_minutes"):
        audit([row()], material=material)


def test_invalid_future_revision_still_fails_closed():
    rows = shifted_rows()
    rows[-1]["actual"] = "9"
    with pytest.raises(ValueError, match="Schedule revision"):
        audit(rows, decision="2026-10-28T13:00:00Z")
