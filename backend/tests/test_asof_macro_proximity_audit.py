"""Synthetic as-of macro proximity regression tests; no market or calendar feed."""
from copy import deepcopy

import pytest

from app.asof_macro_proximity_audit import (
    audit_asof_macro_proximity, fingerprint_scheduled_macro_calendar,
)
from app.frozen_next_open_intent import fingerprint_next_open_intents

T = 1767600000  # Synthetic minute-aligned UTC timestamp.
SOURCE = dict(instrument="XAUUSD", provider="fixture", venue="fixture",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=3)


def manifest(minutes=(0, 60, 120), excluded=False):
    return dict(
        protocol="frozen-next-open-intent-v1", source=dict(SOURCE),
        eligible_intents=[
            dict(path_id=f"p{i}", signal_at=T + m * 60,
                 direction="LONG", stop="95", target="105")
            for i, m in enumerate(minutes)
        ],
        excluded_signals=(
            [dict(path_id="excluded", signal_at=T - 60,
                  reason="PRE_SIGNAL_DATA_GAP")] if excluded else []
        ),
    )


def event(event_id, scheduled_minute, known_minute, impact="HIGH"):
    return dict(event_id=event_id, scheduled_at=T + scheduled_minute * 60,
                known_at=T + known_minute * 60, impact=impact)


def calendar(events=()):
    return dict(protocol="frozen-scheduled-macro-calendar-v1",
                source=dict(provider="fixture", instrument="XAUUSD",
                            snapshot_id="synthetic-v1"),
                events=list(events))


def audit(m=None, c=None, **kwargs):
    m = m if m is not None else manifest()
    c = c if c is not None else calendar()
    return audit_asof_macro_proximity(
        m, fingerprint_next_open_intents(m),
        c, fingerprint_scheduled_macro_calendar(c), **kwargs,
    )


def window(result, minutes):
    return next(w for w in result["windows"] if w["minutes"] == minutes)


def test_empty_calendar_is_not_a_safety_clearance():
    r = audit()
    assert r["eligible_intents"] == 3
    assert window(r, 60)["signals_without_declared_event"] == 3
    assert r["safe_to_trade"] is False
    assert r["independent_calendar_completeness_verified"] is False


def test_known_high_event_in_inclusive_fifteen_minute_window():
    r = audit(c=calendar([event("nfp", 15, -1)]))
    assert window(r, 15)["signals_with_known_high"] == 1
    assert window(r, 15)["known_high_event_observations"] == 1
    assert r["intent_samples"][0]["windows"][0]["known_high_events"] == 1


def test_event_at_exact_negative_boundary_is_included():
    r = audit(c=calendar([event("nfp", -15, -20)]))
    assert window(r, 15)["known_event_observations"] == 1


def test_event_one_minute_outside_fifteen_window_still_in_sixty():
    r = audit(c=calendar([event("nfp", 16, -1)]))
    assert window(r, 15)["known_event_observations"] == 0
    assert window(r, 60)["known_event_observations"] == 2  # also within 60m of the second signal


def test_future_published_event_cannot_be_used_at_signal():
    r = audit(c=calendar([event("late", 0, 1)]))
    w = window(r, 15)
    assert w["known_event_observations"] == 0
    assert w["later_known_event_observations"] == 1
    assert w["signals_without_declared_event"] == 2  # later signals are outside the window


def test_publication_exactly_at_completed_signal_is_known():
    r = audit(c=calendar([event("now", 0, 0)]))
    assert window(r, 15)["known_high_event_observations"] == 1


def test_later_signal_can_see_version_unavailable_to_earlier_signal():
    m = manifest((0, 1))
    c = calendar([event("revision", 1, 1)])
    r = audit(m, c)
    assert window(r, 15)["known_event_observations"] == 1
    assert window(r, 15)["later_known_event_observations"] == 1


def test_low_medium_do_not_masquerade_as_high():
    c = calendar([event("low", 0, -10, "LOW"),
                  event("medium", 1, -10, "MEDIUM")])
    r = audit(c=c)
    assert window(r, 15)["known_event_observations"] == 2
    assert window(r, 15)["known_high_event_observations"] == 0


def test_multiple_same_minute_events_count_separately():
    c = calendar([event("a", 0, -1), event("b", 0, -1)])
    r = audit(c=c)
    assert window(r, 15)["known_event_observations"] == 2


def test_input_order_does_not_change_digest_or_audit_and_does_not_mutate():
    c = calendar([event("a", 0, -1), event("b", 20, -1)])
    before = deepcopy(c)
    r1 = audit(c=c)
    c["events"].reverse()
    r2 = audit(c=c)
    assert r1 == r2
    assert c["events"] == list(reversed(before["events"]))


def test_manifest_or_calendar_tampering_is_rejected():
    m, c = manifest(), calendar([event("a", 0, -1)])
    md, cd = fingerprint_next_open_intents(m), fingerprint_scheduled_macro_calendar(c)
    m["eligible_intents"][0]["target"] = "110"
    with pytest.raises(ValueError, match="Frozen intent fingerprint mismatch"):
        audit_asof_macro_proximity(m, md, c, cd)
    m = manifest()
    c["events"][0]["impact"] = "LOW"
    with pytest.raises(ValueError, match="Calendar fingerprint mismatch"):
        audit_asof_macro_proximity(m, fingerprint_next_open_intents(m), c, cd)


def test_calendar_instrument_mismatch_is_rejected():
    c = calendar()
    c["source"]["instrument"] = "WTIUSD"
    with pytest.raises(ValueError, match="instrument mismatch"):
        audit(c=c)


@pytest.mark.parametrize("bad", [
    dict(event_id="x", scheduled_at=T, known_at=T, impact="REVISED"),
    dict(event_id="x", scheduled_at=T + 1, known_at=T, impact="HIGH"),
    dict(event_id="x", scheduled_at=T, known_at=True, impact="HIGH"),
    dict(event_id="x", scheduled_at=T, known_at=T, impact="HIGH", actual="2.5"),
])
def test_invalid_event_schema_and_clocks_fail_closed(bad):
    with pytest.raises(ValueError):
        fingerprint_scheduled_macro_calendar(calendar([bad]))


def test_duplicate_event_ids_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        audit(c=calendar([event("same", 0, -1), event("same", 1, -1)]))


@pytest.mark.parametrize("limit", [-1, 51, True, 1.5])
def test_sample_limit_must_be_bounded_integer(limit):
    with pytest.raises(ValueError, match="sample limit"):
        audit(sample_limit=limit)


def test_zero_samples_does_not_drop_population_counts():
    r = audit(c=calendar([event("a", 0, -1)]), sample_limit=0)
    assert r["intent_samples"] == []
    assert window(r, 15)["known_event_observations"] == 1


def test_exclusions_are_reported_without_posthoc_filtering():
    r = audit(m=manifest(excluded=True))
    assert r["eligible_intents"] == 3
    assert r["declared_pre_signal_exclusions"] == 1
    assert r["may_exclude_signals"] is False


def test_invalid_hashes_rejected_before_audit():
    m, c = manifest(), calendar()
    with pytest.raises(ValueError, match="calendar SHA-256"):
        audit_asof_macro_proximity(m, fingerprint_next_open_intents(m), c, "wrong")
    with pytest.raises(ValueError, match="manifest SHA-256"):
        audit_asof_macro_proximity(m, "wrong", c, fingerprint_scheduled_macro_calendar(c))
