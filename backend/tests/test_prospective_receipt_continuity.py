"""Synthetic append-only M1 checkpoint regressions; no provider or account."""
from dataclasses import replace

import pytest

from app.expected_bar_manifest import compile_expected_m1_manifest
from app.prospective_receipt_continuity import audit_declared_m1_receipt_continuity

T = 1790000040
BASE = dict(
    provider="fixture", symbol="XAU/USD", venue="synthetic", price_side="BID",
    calendar_id="fixture", calendar_revision="r1",
    calendar_source="operator declared UTC schedule", exclusions_utc=[],
)


def manifest(now, sessions, **changes):
    return compile_expected_m1_manifest(
        **(BASE | {"observed_at_utc": now, "sessions_utc": sessions} | changes))


P = manifest(T + 180, [(T, T + 120)])
C = manifest(T + 300, [(T, T + 120), (T + 180, T + 240)])


def bar(t, **changes):
    return dict({
        "provider": "fixture", "symbol": "XAU/USD", "venue": "synthetic",
        "price_side": "BID", "bar_start_utc": t, "received_at_utc": t + 65,
        "open": 100., "high": 102., "low": 99., "close": 101.,
    } | changes)


def audit(previous=None, current=None, previous_manifest=P, current_manifest=C, **kw):
    return audit_declared_m1_receipt_continuity(
        [bar(T), bar(T + 60)] if previous is None else previous,
        [bar(T), bar(T + 60), bar(T + 180)] if current is None else current,
        previous_manifest, current_manifest, **kw)


def test_clean_append_is_only_internal_continuity():
    r = audit()
    assert r["status"] == "INTERNAL_CONTINUITY_ONLY_NOT_LIVE"
    assert r["retained_unchanged_minutes"] == 2
    assert r["newly_observed_current_expected_minutes"] == 1
    assert r["removed_previous_minutes"] == 0
    assert r["backfilled_prior_expected_minutes"] == 0
    assert r["source_authenticated"] is False
    assert r["live"] is False and r["may_execute_order"] is False
    assert r["input_sha256"] == audit()["input_sha256"]


def test_old_ohlc_rewrite_detected_even_when_both_censuses_complete():
    r = audit(current=[bar(T, close=100.5), bar(T + 60), bar(T + 180)])
    assert r["revised_previous_ohlc_minutes"] == 1
    assert r["status"] == "REVIEW_REQUIRED"
    assert len(r["revised_utc_samples"]) == 1


def test_receipt_timestamp_rewrite_is_not_accepted_as_repolling():
    r = audit(current=[bar(T, received_at_utc=T + 70), bar(T + 60), bar(T + 180)])
    assert r["rewritten_previous_receipt_times"] == 1
    assert r["status"] == "REVIEW_REQUIRED"


def test_old_row_removed_fails_closed():
    r = audit(current=[bar(T), bar(T + 180)])
    assert r["removed_previous_minutes"] == 1
    assert r["status"] == "REVIEW_REQUIRED"


def test_late_backfill_is_not_fresh_new_expected_bar():
    r = audit(previous=[bar(T)])
    assert r["backfilled_prior_expected_minutes"] == 1
    assert r["newly_observed_current_expected_minutes"] == 1
    assert r["status"] == "REVIEW_REQUIRED"


def test_backdated_new_receipt_is_flagged():
    r = audit(previous=[bar(T)], current=[
        bar(T), bar(T + 60, received_at_utc=T + 125), bar(T + 180)])
    assert r["backdated_new_receipt_times"] == 1
    assert r["status"] == "REVIEW_REQUIRED"


def test_current_unexpected_minute_is_not_counted_as_new_expected():
    r = audit(current=[bar(T), bar(T + 60), bar(T + 120), bar(T + 180)])
    assert r["current_census_status"] == "REVIEW_REQUIRED"
    assert r["newly_observed_current_expected_minutes"] == 1
    assert r["status"] == "REVIEW_REQUIRED"


def test_bounded_sample_redaction():
    r = audit(current=[bar(T, close=100.5), bar(T + 60), bar(T + 180)], sample_limit=0)
    assert r["revised_previous_ohlc_minutes"] == 1
    assert r["revised_utc_samples"] == []


@pytest.mark.parametrize("bad", [-1, 51, True, "10"])
def test_sample_limit_must_be_bounded_integer(bad):
    with pytest.raises(ValueError):
        audit(sample_limit=bad)


def test_mixed_identity_calendar_and_backward_observation_refused():
    with pytest.raises(ValueError):
        audit(current_manifest=manifest(
            T + 300, [(T, T + 120), (T + 180, T + 240)], price_side="ASK"))
    with pytest.raises(ValueError):
        audit(current_manifest=manifest(
            T + 300, [(T, T + 120), (T + 180, T + 240)], calendar_revision="r2"))
    with pytest.raises(ValueError):
        audit(current_manifest=P)
    with pytest.raises(ValueError):
        audit(current_manifest=manifest(T + 300, [(T, T + 60), (T + 180, T + 240)]))


def test_tampered_manifest_and_invalid_rows_refused():
    with pytest.raises(ValueError):
        audit(current_manifest=replace(C, manifest_sha256="0" * 64))
    with pytest.raises(ValueError):
        audit(current=[bar(T), bar(T + 60), bar(T + 180, price_side="ASK")])


def test_duplicate_rows_remain_review_required():
    r = audit(current=[bar(T), bar(T), bar(T + 60), bar(T + 180)])
    assert r["current_census_status"] == "REVIEW_REQUIRED"
    assert r["status"] == "REVIEW_REQUIRED"
