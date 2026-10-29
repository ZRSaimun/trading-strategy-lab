"""Synthetic-only regression tests; no external event calendar is authenticated."""
from copy import deepcopy
import pytest
from app.offline_event_asof_guard import audit_declared_event_asof


def row(revision=1, kind="schedule", scheduled="2026-10-28T18:00:00Z",
        published="2026-10-28T12:00:00Z", observed="2026-10-28T12:01:00Z",
        forecast="3.5", actual=None, event_id="FOMC"):
    return dict(event_id=event_id, revision=revision, kind=kind,
                scheduled_utc=scheduled, published_utc=published,
                observed_utc=observed, forecast=forecast, actual=actual)


def run(rows, decision="2026-10-28T17:00:00Z"):
    return audit_declared_event_asof(rows, decision_utc=decision, source_id="synthetic-calendar")


def test_pre_news_schedule_visible_without_actual():
    report = run([row()])
    assert report["events"][0]["actual"] is None
    assert report["events"][0]["result_available"] is False
    assert report["trade_authorized"] is False


def test_result_only_visible_after_observed():
    rows = [row(), row(2, "result", published="2026-10-28T18:01:00Z",
                       observed="2026-10-28T18:02:00Z", actual="3.7")]
    assert run(rows, "2026-10-28T18:01:00Z")["events"][0]["actual"] is None
    assert run(rows, "2026-10-28T18:02:00Z")["events"][0]["actual"] is None
    assert run(rows, "2026-10-28T18:03:00Z")["events"][0]["actual"] == "3.7"


def test_future_revision_cannot_change_past_snapshot():
    base = [row()]
    future = row(2, "schedule", scheduled="2026-10-28T19:00:00Z",
                 published="2026-10-28T17:01:00Z", observed="2026-10-28T17:02:00Z")
    assert run(base) == run(base+[future])


def test_result_in_decision_minute_is_excluded():
    rows = [row(), row(2, "result", published="2026-10-28T18:00:00Z",
                       observed="2026-10-28T18:00:00Z", actual="3.7")]
    assert run(rows, "2026-10-28T18:00:00Z")["events"][0]["actual"] is None
    assert run(rows, "2026-10-28T18:01:00Z")["events"][0]["actual"] == "3.7"


def test_unobserved_schedule_not_visible():
    assert run([row()], "2026-10-28T11:00:00Z")["visible_event_count"] == 0


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r.update(actual="3.6"), "Schedule revision"),
    (lambda r: r.update(forecast="NaN"), "Finite"),
    (lambda r: r.update(observed_utc="2026-10-28T11:59:00Z"), "Observation"),
    (lambda r: r.update(revision=True), "revision"),
    (lambda r: r.update(extra="x"), "Closed-schema"),
    (lambda r: r.update(scheduled_utc="2026-10-28T19:00:01Z"), "minute"),
    (lambda r: r.update(published_utc="2026-10-28T13:00:00+01:00"), "UTC"),
])
def test_invalid_revision_rejected(mutate, match):
    x = row()
    mutate(x)
    with pytest.raises(ValueError, match=match):
        run([x])


def test_duplicate_revision_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        run([row(), row(observed="2026-10-28T13:00:00Z")])


def test_nonmonotonic_revision_observation_rejected():
    with pytest.raises(ValueError, match="clocks"):
        run([row(), row(2, observed="2026-10-28T12:00:00Z")])


def test_result_before_event_rejected():
    with pytest.raises(ValueError, match="post-event"):
        run([row(), row(2, "result", actual="3.7")])


def test_schedule_after_result_rejected():
    with pytest.raises(ValueError, match="after result"):
        run([row(), row(2, "result", published="2026-10-28T18:00:00Z",
                        observed="2026-10-28T18:00:00Z", actual="3.7"),
             row(3, "schedule", published="2026-10-28T18:01:00Z",
                 observed="2026-10-28T18:01:00Z")])


def test_deterministic_no_mutation_and_order_independence():
    rows = [row(event_id="A"), row(event_id="B")]
    before = deepcopy(rows)
    assert run(rows) == run(list(reversed(rows)))
    assert rows == before


def test_missing_revision_rejected():
    with pytest.raises(ValueError, match="Missing"):
        run([row(), row(3, observed="2026-10-28T13:00:00Z")])


def test_result_decimal_string_normalization():
    rows = [row(), row(2, "result", published="2026-10-28T18:00:00Z",
                       observed="2026-10-28T18:00:00Z", actual="3.700")]
    assert run(rows, "2026-10-28T18:01:00Z")["events"][0]["actual"] == "3.7"


def test_result_cannot_rewrite_pre_release_schedule():
    rows = [row(), row(2, "result", scheduled="2026-10-28T17:00:00Z",
                       published="2026-10-28T18:01:00Z",
                       observed="2026-10-28T18:02:00Z", actual="3.7")]
    with pytest.raises(ValueError, match="latest schedule"):
        run(rows, "2026-10-28T18:03:00Z")


def test_result_cannot_rewrite_pre_release_forecast():
    rows = [row(), row(2, "result", published="2026-10-28T18:01:00Z",
                       observed="2026-10-28T18:02:00Z", forecast="4.0",
                       actual="3.7")]
    with pytest.raises(ValueError, match="latest schedule"):
        run(rows, "2026-10-28T18:03:00Z")


def test_long_decimal_preserved_without_context_rounding():
    precise = "1.234567890123456789012345678901"
    assert run([row(forecast=precise)])["events"][0]["forecast"] == precise


@pytest.mark.parametrize("value", ["1e-31", "0e-1000000", "1e31"])
def test_unbounded_or_oversized_decimal_rejected(value):
    with pytest.raises(ValueError, match="Bounded|Finite"):
        run([row(forecast=value)])


def test_negative_zero_is_canonical_and_deterministic():
    assert run([row(forecast="-0.000")])["events"][0]["forecast"] == "0"


def test_first_schedule_observed_after_event_rejected():
    with pytest.raises(ValueError, match="before its event"):
        run([row(published="2026-10-28T18:01:00Z",
                 observed="2026-10-28T18:02:00Z")], "2026-10-28T19:00:00Z")


def test_first_schedule_observed_exactly_at_event_rejected():
    with pytest.raises(ValueError, match="before its event"):
        run([row(published="2026-10-28T18:00:00Z",
                 observed="2026-10-28T18:00:00Z")], "2026-10-28T19:00:00Z")


def test_post_release_forecast_revision_rejected():
    rows = [row(), row(2, "schedule", published="2026-10-28T18:01:00Z",
                       observed="2026-10-28T18:02:00Z", forecast="3.8")]
    with pytest.raises(ValueError, match="before its event"):
        run(rows, "2026-10-28T19:00:00Z")


def test_post_original_event_time_postponement_rejected():
    rows = [row(), row(2, "schedule", scheduled="2026-10-28T19:00:00Z",
                       published="2026-10-28T18:01:00Z",
                       observed="2026-10-28T18:02:00Z")]
    with pytest.raises(ValueError, match="prior event time"):
        run(rows, "2026-10-28T19:30:00Z")


def test_postponement_at_original_event_boundary_rejected():
    rows = [row(), row(2, "schedule", scheduled="2026-10-28T19:00:00Z",
                       published="2026-10-28T18:00:00Z",
                       observed="2026-10-28T18:00:00Z")]
    with pytest.raises(ValueError, match="prior event time"):
        run(rows, "2026-10-28T19:30:00Z")


def test_pre_event_reschedule_remains_visible_as_of():
    rows = [row(), row(2, "schedule", scheduled="2026-10-28T19:00:00Z",
                       published="2026-10-28T17:01:00Z",
                       observed="2026-10-28T17:02:00Z", forecast="3.6")]
    assert run(rows, "2026-10-28T17:01:00Z")["events"][0]["revision"] == 1
    assert run(rows, "2026-10-28T17:02:00Z")["events"][0]["revision"] == 1
    visible = run(rows, "2026-10-28T17:03:00Z")["events"][0]
    assert visible["revision"] == 2
    assert visible["forecast"] == "3.6"
    assert visible["scheduled_utc"] == "2026-10-28T19:00:00+00:00"


def test_first_schedule_stamped_in_decision_minute_is_not_visible():
    report = run([row()], "2026-10-28T12:01:00Z")
    assert report["visible_revision_count"] == 0
    assert report["visible_event_count"] == 0
    assert report["events"] == []
    assert run([row()], "2026-10-28T12:02:00Z")["visible_event_count"] == 1


def test_same_minute_result_does_not_change_prior_snapshot_or_count():
    schedule = row()
    result = row(2, "result", published="2026-10-28T18:00:00Z",
                 observed="2026-10-28T18:00:00Z", actual="3.7")
    before = run([schedule], "2026-10-28T18:00:00Z")
    same_minute = run([schedule, result], "2026-10-28T18:00:00Z")
    assert same_minute == before
    assert same_minute["visible_revision_count"] == 1
    after = run([schedule, result], "2026-10-28T18:01:00Z")
    assert after["visible_revision_count"] == 2
    assert after["events"][0]["actual"] == "3.7"


def test_research_envelope_binds_source_without_changing_legacy_event_digest():
    records = [row()]
    first = audit_declared_event_asof(
        records, decision_utc="2026-10-28T17:00:00Z", source_id="provider-A"
    )
    second = audit_declared_event_asof(
        records, decision_utc="2026-10-28T17:00:00Z", source_id="provider-B"
    )
    assert first["events"] == second["events"]
    assert first["visible_snapshot_sha256"] == second["visible_snapshot_sha256"]
    assert first["research_envelope_sha256"] != second["research_envelope_sha256"]
    assert first["research_envelope_schema_version"] == 1


def test_research_envelope_binds_decision_even_when_events_unchanged():
    before = run([row()], "2026-10-28T16:00:00Z")
    after = run([row()], "2026-10-28T17:00:00Z")
    assert before["events"] == after["events"]
    assert before["visible_snapshot_sha256"] == after["visible_snapshot_sha256"]
    assert before["research_envelope_sha256"] != after["research_envelope_sha256"]


def test_research_envelope_future_revision_invariant_and_order_independent():
    base = [row(event_id="A"), row(event_id="B")]
    later = row(2, "schedule", event_id="A",
                scheduled="2026-10-28T19:00:00Z",
                published="2026-10-28T17:01:00Z",
                observed="2026-10-28T17:02:00Z")
    first = run(base)
    assert run(list(reversed(base))) == first
    assert run(base + [later]) == first


def test_research_envelope_digest_matches_independent_canonical_payload():
    import hashlib
    import json

    report = run([row()])
    expected = {
        "schema_version": 1,
        "source_id": report["source_id"],
        "decision_utc": report["decision_utc"],
        "visible_revision_count": report["visible_revision_count"],
        "events": report["events"],
    }
    canonical = json.dumps(
        expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert report["research_envelope_sha256"] == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_empty_event_envelope_still_binds_declared_source():
    a = audit_declared_event_asof(
        [], decision_utc="2026-10-28T17:00:00Z", source_id="A"
    )
    b = audit_declared_event_asof(
        [], decision_utc="2026-10-28T17:00:00Z", source_id="B"
    )
    assert a["visible_event_count"] == b["visible_event_count"] == 0
    assert a["research_envelope_sha256"] != b["research_envelope_sha256"]


def test_v2_history_distinguishes_different_intermediate_forecasts():
    # Both histories have the same latest visible record and revision count.
    # The v1 event and envelope hashes cannot distinguish them.
    first = [row(), row(2, observed="2026-10-28T13:01:00Z",
                        published="2026-10-28T13:00:00Z", forecast="3.6"),
             row(3, observed="2026-10-28T14:01:00Z",
                 published="2026-10-28T14:00:00Z", forecast="3.7")]
    second = deepcopy(first)
    second[1]["forecast"] = "3.8"
    a, b = run(first), run(second)
    assert a["events"] == b["events"]
    assert a["visible_revision_count"] == b["visible_revision_count"] == 3
    assert a["visible_snapshot_sha256"] == b["visible_snapshot_sha256"]
    assert a["research_envelope_sha256"] == b["research_envelope_sha256"]
    assert a["visible_revision_history_sha256"] != b["visible_revision_history_sha256"]
    assert a["research_envelope_v2_sha256"] != b["research_envelope_v2_sha256"]


def test_v2_history_excludes_future_and_same_minute_revisions():
    first = row()
    future = row(2, "schedule", scheduled="2026-10-28T19:00:00Z",
                 published="2026-10-28T17:00:00Z",
                 observed="2026-10-28T17:01:00Z", forecast="3.6")
    baseline = run([first])
    assert run([first, future]) == baseline
    assert run([first, future], "2026-10-28T17:01:00Z")["visible_revision_history_sha256"] == baseline["visible_revision_history_sha256"]
    later = run([first, future], "2026-10-28T17:02:00Z")
    assert later["visible_revision_history_sha256"] != baseline["visible_revision_history_sha256"]


def test_v2_history_is_row_order_independent_and_does_not_mutate():
    rows = [row(event_id="B"), row(event_id="A"),
            row(2, event_id="A", published="2026-10-28T13:00:00Z",
                observed="2026-10-28T13:01:00Z", forecast="3.6")]
    original = deepcopy(rows)
    assert run(rows) == run(list(reversed(rows)))
    assert rows == original


def test_v2_envelope_matches_independent_canonical_reconstruction():
    import hashlib
    import json

    rows = [row(), row(2, published="2026-10-28T13:00:00Z",
                       observed="2026-10-28T13:01:00Z", forecast="3.6")]
    report = run(rows)
    visible = [
        dict(event_id=r["event_id"], revision=r["revision"], kind=r["kind"],
             scheduled_utc="2026-10-28T18:00:00+00:00",
             published_utc=r["published_utc"].replace("Z", "+00:00"),
             observed_utc=r["observed_utc"].replace("Z", "+00:00"),
             forecast=r["forecast"], actual=None)
        for r in rows
    ]
    history = json.dumps(visible, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    history_sha = hashlib.sha256(history.encode("utf-8")).hexdigest()
    assert report["visible_revision_history_sha256"] == history_sha
    envelope = {
        "schema_version": 2, "source_id": report["source_id"],
        "decision_utc": report["decision_utc"],
        "visible_revision_count": 2,
        "visible_revision_history_sha256": history_sha, "events": report["events"],
    }
    expected = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert report["research_envelope_v2_schema_version"] == 2
    assert report["research_envelope_v2_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_v2_empty_history_binds_source_and_cutoff():
    a = audit_declared_event_asof([], decision_utc="2026-10-28T17:00:00Z", source_id="A")
    b = audit_declared_event_asof([], decision_utc="2026-10-28T17:00:00Z", source_id="B")
    c = audit_declared_event_asof([], decision_utc="2026-10-28T17:01:00Z", source_id="A")
    assert a["visible_revision_history_sha256"] == b["visible_revision_history_sha256"]
    assert a["research_envelope_v2_sha256"] != b["research_envelope_v2_sha256"]
    assert a["research_envelope_v2_sha256"] != c["research_envelope_v2_sha256"]
