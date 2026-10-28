"""Synthetic census-output integrity tests; no market claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from app.offline_news_spike_attrition import audit_news_spike_attrition

T = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


def stamp(i):
    return (T + timedelta(minutes=i)).isoformat()


def event(name, offset, spike="up", positions=None, missing=()):
    positions = positions or {"5": "above_pre_high", "15": "above_pre_high",
                              "30": "inside_pre_range", "60": "below_pre_low"}
    hs = {}
    for h in ("5", "15", "30", "60"):
        if int(h) in missing:
            hs[h] = {"status": "insufficient_complete_minutes", "position": None, "aligned": None}
        else:
            pos = positions[h]
            aligned = ((spike == "up" and pos == "above_pre_high") or
                       (spike == "down" and pos == "below_pre_low")) if spike in ("up", "down") else None
            hs[h] = {"status": "observed", "position": pos, "aligned": aligned}
    return {"event_id": name, "event_utc": stamp(offset), "status": "observed",
            "spike": spike, "horizons": hs}


def report(events=None):
    return {"research_only": True, "source_id": "synthetic-XAUUSD-BID",
            "as_of_utc": stamp(500), "pre_minutes": 15,
            "first_reaction_minutes": 5, "events": events if events is not None else []}


def test_empty_population_is_not_success():
    out = audit_news_spike_attrition(report())
    assert out["event_count"] == 0
    assert out["horizons"]["directional_total"]["15"]["observed_alignment_fraction"] is None


def test_known_rejection_and_missing_horizon_bounds():
    rows = [event("up", 0, missing=(30, 60)), event("down", 90, spike="down")]
    out = audit_news_spike_attrition(report(rows))
    h = out["horizons"]["directional_total"]["30"]
    assert (h["eligible"], h["observed"], h["aligned"], h["not_aligned"], h["unknown"]) == (2, 1, 0, 1, 1)
    assert h["observed_alignment_fraction"] == "0.000000"
    assert h["all_eligible_lower_bound"] == "0.000000"
    assert h["all_eligible_upper_bound"] == "0.500000"
    assert out["horizons"]["up"]["5"]["observed_alignment_fraction"] == "1.000000"


def test_quarantined_and_nondirectional_not_discarded():
    bad = {"event_id": "missing", "event_utc": stamp(180), "status": "missing_pre_event_minutes", "spike": None, "horizons": None}
    out = audit_news_spike_attrition(report([event("both", 0, spike="both"), event("none", 90, spike="none"), bad]))
    assert out["event_count"] == 3
    assert out["directional_eligible"] == 0
    assert out["event_populations"]["both"] == 1
    assert out["event_populations"]["missing_pre_event_minutes"] == 1


@pytest.mark.parametrize("mutation", [
    lambda x: x["events"][0]["horizons"]["15"].update(aligned=False),
    lambda x: x["events"][0]["horizons"]["15"].update(position=None),
    lambda x: x["events"][0]["horizons"]["15"].update(extra="bad"),
    lambda x: x["events"][0]["horizons"].pop("30"),
    lambda x: x["events"][0].update(extra="bad"),
    lambda x: x.update(research_only=1),
    lambda x: x.update(pre_minutes=True),
    lambda x: x["events"][0].update(spike="invalid"),
    lambda x: x["events"][0].update(event_utc="2026-10-28T19:00:00+01:00"),
    lambda x: x["events"][0]["horizons"]["60"].update(status="insufficient_complete_minutes", aligned=True, position=None),
])
def test_fail_closed_on_tampering(mutation):
    x = report([event("one", 0)])
    mutation(x)
    with pytest.raises(ValueError):
        audit_news_spike_attrition(x)


def test_reject_duplicate_and_overlapping_events():
    with pytest.raises(ValueError):
        audit_news_spike_attrition(report([event("a", 0), event("a", 90)]))
    with pytest.raises(ValueError):
        audit_news_spike_attrition(report([event("a", 0), event("b", 74)]))


def test_missing_early_horizon_cannot_be_followed_by_observed_later():
    x = report([event("one", 0, missing=(30, 60))])
    x["events"][0]["horizons"]["60"] = {"status": "observed", "position": "inside_pre_range", "aligned": False}
    with pytest.raises(ValueError, match="completeness"):
        audit_news_spike_attrition(x)


def test_horizon_not_yet_complete_rejected():
    x = report([event("one", 0)])
    x["as_of_utc"] = stamp(30)
    with pytest.raises(ValueError, match="Noncausal"):
        audit_news_spike_attrition(x)


def test_no_input_mutation():
    x = report([event("one", 0)])
    original = deepcopy(x)
    audit_news_spike_attrition(x)
    assert x == original
