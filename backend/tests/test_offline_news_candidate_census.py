"""Synthetic historical decision-time news candidate census tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.offline_news_candidate_census import audit_declared_news_candidate_census


def row(event_id="A", minute=0, observed="2026-10-28T12:00:00Z", revision=1):
    event_time = datetime(2026, 10, 28, 18, tzinfo=timezone.utc) + timedelta(minutes=minute)
    return {"event_id": event_id, "revision": revision, "kind": "schedule",
            "scheduled_utc": event_time.isoformat(), "published_utc": observed,
            "observed_utc": observed, "forecast": "3", "actual": None}


def run(rows, times=None, **kwargs):
    if times is None:
        times = ["2026-10-28T17:59:00Z", "2026-10-28T18:00:00Z",
                 "2026-10-28T18:01:00Z", "2026-10-28T19:00:00Z"]
    policy = {"before_minutes": 15, "after_minutes": 15}
    policy.update(kwargs)
    return audit_declared_news_candidate_census(
        rows, decision_utcs=times, source_id="declared-source", **policy,
    )


def test_empty_calendar_never_clears_any_candidate():
    x = run([])
    assert x["candidate_count"] == x["unverified_no_window_count"] == 4
    assert not x["coverage_verified"] and not x["trade_authorized"]
    assert all(not r["eligible_for_event_attribution"] for r in x["records"])


def test_isolated_and_no_window_separated_without_claiming_causation():
    x = run([row()])
    assert x["unverified_isolated_count"] == 3
    assert x["unverified_no_window_count"] == 1
    assert x["records"][0]["declared_window_event_ids"] == ["A"]


def test_boundary_touching_neighbor_confounds_even_if_not_active_at_decision():
    x = run([row("A"), row("B", 30)], times=["2026-10-28T18:00:00Z"])
    assert x["confounded_declared_count"] == 1
    assert x["records"][0]["declared_window_event_ids"] == ["A"]
    assert x["records"][0]["declared_cluster_event_ids"] == [["A", "B"]]


def test_late_schedule_becomes_visible_only_at_next_minute():
    rows = [row("A"), row("B", 30, observed="2026-10-28T18:00:00Z")]
    x = run(rows, times=["2026-10-28T18:00:00Z", "2026-10-28T18:01:00Z"])
    assert [r["attribution_exclusion_reason"] for r in x["records"]] == [
        "DECLARED_SINGLE_WINDOW_UNVERIFIED", "CONFOUNDED_DECLARED_WINDOWS"
    ]


def test_future_invisible_revision_does_not_rewrite_prior_candidate():
    initial = [row("A")]
    future = row("B", 30, observed="2026-10-28T18:00:00Z")
    x = run(initial, times=["2026-10-28T18:00:00Z"])
    assert x == run(initial + [future], times=["2026-10-28T18:00:00Z"])


def test_deterministic_order_immutability_and_source_isolation():
    rows = [row("A"), row("B", 30)]
    original = deepcopy(rows)
    x = run(rows)
    assert x == run(list(reversed(rows)))
    assert rows == original
    y = audit_declared_news_candidate_census(
        rows, decision_utcs=[r["decision_utc"] for r in x["records"]],
        source_id="different", before_minutes=15, after_minutes=15,
    )
    assert x["candidate_census_sha256"] != y["candidate_census_sha256"]


def test_hash_reconstruction_and_population_reconciliation():
    x = run([row("A"), row("B", 30)])
    assert x["candidate_count"] == (x["confounded_declared_count"]
        + x["unverified_isolated_count"] + x["unverified_no_window_count"])
    envelope = {"schema_version": 1, "source_id": x["source_id"],
                "before_minutes": x["before_minutes"], "after_minutes": x["after_minutes"],
                "candidate_decision_utcs": [r["decision_utc"] for r in x["records"]],
                "records": x["records"]}
    digest = hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()
    assert digest == x["candidate_census_sha256"]


@pytest.mark.parametrize("times", [[], "2026-10-28T18:00:00Z", [None],
    ["2026-10-28T18:00:30Z"], ["2026-10-28T18:00:00+01:00"],
    ["2026-10-28T18:00:00Z", "2026-10-28T18:00:00Z"],
    ["2026-10-28T18:01:00Z", "2026-10-28T18:00:00Z"],
    ["2026-10-28T18:00:00Z"] * 257])
def test_invalid_candidate_sequence_fails_closed(times):
    with pytest.raises(ValueError):
        run([row()], times=times)


def test_invalid_future_revision_still_fails_closed():
    bad = row("B", 30, observed="2026-10-28T18:00:00Z")
    bad["actual"] = "3"
    with pytest.raises(ValueError):
        run([row("A"), bad], times=["2026-10-28T18:00:00Z"])


def test_invalid_policy_fails_closed():
    with pytest.raises(ValueError):
        run([row()], times=["2026-10-28T18:00:00Z"], after_minutes=1441)
