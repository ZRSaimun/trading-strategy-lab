"""Synthetic-only tests: no network, accounts, prices or real provider receipts."""
from copy import deepcopy

import pytest

from app.declared_completed_m1_receipts import audit_declared_completed_m1_receipts

T = 1_790_000_100
assert T % 60 == 0


def row(start=T, *, event="e1", received=None):
    return dict(
        event_id=event, provider="synthetic", instrument="XAU/USD",
        source_id="test:feed", price_side="mid", minute_start_utc=start,
        finalized_at_utc=start + 61,
        received_at_utc=start + 62 if received is None else received,
        is_final=True, open="100.00", high="101.00", low="99.00", close="100.50",
    )


def audit(rows, **kw):
    return audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", as_of_utc=T + 240, **kw
    )


def test_one_completed_receipt_is_never_authenticated_or_live():
    report = audit([row()])
    assert report["structurally_clean"] is True
    assert report["declared_freshness_within_budget"] is True
    assert report["latest_candle_end_age_seconds"] == 180
    assert report["market_data_live"] is False
    assert report["research_ready"] is False
    assert report["may_execute_order"] is False
    assert report["licensing_verified"] is False


def test_digest_is_deterministic_and_input_unchanged():
    rows = [row()]
    original = deepcopy(rows)
    assert audit(rows) == audit(rows)
    assert rows == original
    altered = deepcopy(rows)
    altered[0]["close"] = "100.51"
    assert audit(rows)["receipt_inventory_sha256"] != audit(altered)["receipt_inventory_sha256"]


def test_gap_is_observation_not_calendar_proof():
    report = audit([row(T, event="e1"), row(T + 120, event="e2", received=T + 182)])
    assert report["observed_gap_minutes_not_proven_missing"] == 1
    assert report["structurally_clean"] is True
    assert report["session_calendar_verified"] is False


def test_declared_expected_inventory_detects_missing_and_extra():
    report = audit([row()], expected_utc_minutes=[T, T + 60])
    assert report["missing_declared_expected_minutes"] == 1
    assert report["extra_minutes_outside_declared_expected"] == 0
    assert report["structurally_clean"] is False
    report2 = audit([row()], expected_utc_minutes=[T + 60])
    assert report2["extra_minutes_outside_declared_expected"] == 1


def test_duplicate_minute_is_quarantined_even_if_ohlc_equal():
    report = audit([row(event="e1"), row(event="e2", received=T + 63)])
    assert report["duplicate_minute_rows"] == 1
    assert report["structurally_clean"] is False


def test_backward_minute_is_quarantined():
    report = audit([row(T + 60, event="e1", received=T + 123),
                    row(T, event="e2", received=T + 124)])
    assert report["backward_candle_events"] == 1
    assert report["structurally_clean"] is False


def test_transport_lag_and_stale_candle_are_separate():
    late = row(received=T + 120)
    report = audit([late], max_transport_lag_seconds=30)
    assert report["transport_lag_exceeded_rows"] == 1
    assert report["declared_freshness_within_budget"] is False
    assert audit([row()], max_age_seconds=179)["declared_freshness_within_budget"] is False


@pytest.mark.parametrize("field,value", [
    ("event_id", "bad\\n"), ("provider", "other"), ("instrument", "EUR/USD"),
    ("source_id", "other"), ("price_side", "bid"), ("is_final", False),
    ("is_final", 1), ("minute_start_utc", T + 1),
    ("minute_start_utc", True), ("finalized_at_utc", T + 59),
    ("received_at_utc", T + 60), ("received_at_utc", T + 241),
    ("open", "NaN"), ("high", "Infinity"), ("low", "-1"),
    ("close", "1e10"), ("high", "99"), ("low", "102"),
])
def test_malformed_or_mixed_receipts_fail_closed(field, value):
    bad = row()
    bad[field] = value
    with pytest.raises(ValueError):
        audit([bad])


def test_duplicate_event_id_rejected():
    with pytest.raises(ValueError, match="Duplicate source event"):
        audit([row(), row(received=T + 63)])


def test_receipt_clock_regression_rejected():
    with pytest.raises(ValueError, match="ingestion timestamps"):
        audit([row(event="e1", received=T + 100),
               row(T + 60, event="e2", received=T + 99)])


@pytest.mark.parametrize("expected", [[T, T], [T + 1], [T + 60, T], [True]])
def test_bad_expected_inventory_rejected(expected):
    with pytest.raises(ValueError):
        audit([row()], expected_utc_minutes=expected)


@pytest.mark.parametrize("kwargs", [
    {"max_age_seconds": True}, {"max_age_seconds": 3601},
    {"max_transport_lag_seconds": -1}, {"max_transport_lag_seconds": 301},
])
def test_unsafe_budgets_rejected(kwargs):
    with pytest.raises(ValueError):
        audit([row()], **kwargs)


def test_extra_keys_and_empty_inventory_rejected():
    with pytest.raises(ValueError):
        audit([])
    bad = row()
    bad["license_verified"] = True
    with pytest.raises(ValueError):
        audit([bad])
