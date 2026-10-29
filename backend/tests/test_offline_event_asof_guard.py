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
    assert run(rows, "2026-10-28T18:02:00Z")["events"][0]["actual"] == "3.7"


def test_future_revision_cannot_change_past_snapshot():
    base = [row()]
    future = row(2, "schedule", scheduled="2026-10-28T19:00:00Z",
                 published="2026-10-28T17:01:00Z", observed="2026-10-28T17:02:00Z")
    assert run(base) == run(base+[future])


def test_result_at_event_time_permitted():
    rows = [row(), row(2, "result", published="2026-10-28T18:00:00Z",
                       observed="2026-10-28T18:00:00Z", actual="3.7")]
    assert run(rows, "2026-10-28T18:00:00Z")["events"][0]["actual"] == "3.7"


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
