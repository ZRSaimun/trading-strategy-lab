"""Synthetic causal completion tests for disconnected news-spike research."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.offline_news_spike_persistence import census_news_spike_persistence
from app.offline_news_spike_attrition import audit_news_spike_attrition


BASE = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)


def stamp(offset):
    return (BASE + timedelta(minutes=offset)).isoformat()


def candles(end, *, missing=()):
    rows = []
    for i in range(-15, end):
        if i in missing:
            continue
        high, close = ("103", "102") if i == 0 else ("101", "100")
        rows.append({"time": stamp(i), "open": "100", "high": high,
                     "low": "99", "close": close})
    return rows


def run(end, *, as_of=None, missing=()):
    return census_news_spike_persistence(
        candles(end, missing=missing),
        [{"event_id": "synthetic", "time": stamp(0)}],
        as_of_utc=stamp(end if as_of is None else as_of),
        source_id="synthetic-bid",
    )


@pytest.mark.parametrize("end", [0, 1, 2, 4])
def test_incomplete_first_five_is_pending_not_missing(end):
    report = run(end)
    event = report["events"][0]
    assert event["status"] == "pending_first_five_completion"
    assert event["spike"] is None and event["horizons"] is None
    audit = audit_news_spike_attrition(report)
    assert audit["event_populations"]["pending_first_five_completion"] == 1
    assert audit["event_populations"]["missing_first_five_minutes"] == 0
    assert audit["directional_eligible"] == 0


def test_missing_after_maturity_is_quarantined():
    report = run(5, missing=(2,))
    assert report["events"][0]["status"] == "missing_first_five_minutes"
    audit = audit_news_spike_attrition(report)
    assert audit["event_populations"]["missing_first_five_minutes"] == 1


def test_completed_reaction_is_observed():
    report = run(5)
    assert report["events"][0]["status"] == "observed"
    assert report["events"][0]["spike"] == "up"
    assert audit_news_spike_attrition(report)["directional_eligible"] == 1


def test_reject_fabricated_missing_before_maturity():
    report = run(4)
    report["events"][0]["status"] = "missing_first_five_minutes"
    with pytest.raises(ValueError, match="completion cutoff"):
        audit_news_spike_attrition(report)


def test_reject_fabricated_pending_after_maturity():
    report = run(5, missing=(2,))
    report["events"][0]["status"] = "pending_first_five_completion"
    with pytest.raises(ValueError, match="completion cutoff"):
        audit_news_spike_attrition(report)


def test_reject_fabricated_early_observation():
    report = run(5)
    report["as_of_utc"] = stamp(4)
    with pytest.raises(ValueError, match="first-five completion"):
        audit_news_spike_attrition(report)


def test_reject_fabricated_pending_outcome():
    report = run(4)
    report["events"][0]["spike"] = "up"
    with pytest.raises(ValueError, match="fabricated outcome"):
        audit_news_spike_attrition(report)


def test_no_mutation_and_replay_is_deterministic():
    report = run(4)
    before = deepcopy(report)
    assert audit_news_spike_attrition(report) == audit_news_spike_attrition(report)
    assert report == before
