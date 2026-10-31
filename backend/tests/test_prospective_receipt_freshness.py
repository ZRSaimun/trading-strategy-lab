"""Fresh replays and unexpected receipts must never launder stale expected bars."""
import pytest

from app.prospective_receipt_census import audit_declared_m1_receipts

T = 1790000040
IDENTITY = dict(provider="fixture", symbol="XAU/USD", venue="synthetic", price_side="BID")


def bar(t, received):
    return dict(**IDENTITY, bar_start_utc=t, received_at_utc=received,
                open=100., high=102., low=99., close=101.)


def audit(receipts, expected, now, **limits):
    return audit_declared_m1_receipts(receipts, expected, observed_at_utc=now,
                                      **IDENTITY, **limits)


def test_fresh_replay_cannot_hide_stale_candle_close():
    now = T + 600
    report = audit([bar(T, now), bar(T+60, now)], [T, T+60], now,
                   max_receipt_lag_seconds=1000)
    assert report["stale_declared_observation"] is False
    assert report["stale_expected_receipts"] is False
    assert report["seconds_since_latest_expected_close"] == 480
    assert report["stale_expected_candle"] is True
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["live"] is False and report["may_execute_order"] is False


def test_fresh_unexpected_receipt_cannot_hide_stale_expected_receipts():
    now = T + 360
    report = audit([bar(T, T+65), bar(T+60, T+125), bar(T+240, now)],
                   [T, T+60], now, max_expected_close_age_seconds=500)
    assert report["stale_declared_observation"] is False
    assert report["stale_expected_receipts"] is True
    assert report["stale_expected_candle"] is False
    assert report["unexpected_observed_minutes"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_current_expected_close_passes_but_is_not_live():
    now = T + 180
    report = audit([bar(T+60, T+125), bar(T+120, T+180)],
                   [T+60, T+120], now)
    assert report["seconds_since_latest_expected_close"] == 0
    assert report["stale_expected_candle"] is False
    assert report["stale_expected_receipts"] is False
    assert report["status"] == "INTERNAL_CENSUS_ONLY_NOT_LIVE"
    assert report["source_authenticated"] is False


def test_age_threshold_changes_fingerprint_and_status():
    now = T + 360
    receipts = [bar(T+120, T+355)]
    old = audit(receipts, [T+120], now, max_receipt_lag_seconds=300,
                max_expected_close_age_seconds=300)
    strict = audit(receipts, [T+120], now, max_receipt_lag_seconds=300,
                   max_expected_close_age_seconds=179)
    assert old["stale_expected_candle"] is False
    assert strict["stale_expected_candle"] is True
    assert old["input_sha256"] != strict["input_sha256"]


@pytest.mark.parametrize("bad", [-1, 1.5, True, "180", None])
def test_invalid_expected_age_threshold_rejected(bad):
    with pytest.raises(ValueError):
        audit([bar(T, T+65)], [T], T+90, max_expected_close_age_seconds=bad)


def test_empty_expected_receipts_cannot_pass_even_with_fresh_unexpected():
    now = T + 300
    report = audit([bar(T+180, now)], [T], now, max_expected_close_age_seconds=1000)
    assert report["stale_expected_receipts"] is True
    assert report["seconds_since_last_expected_receipt"] is None
    assert report["missing_expected_minutes"] == 1
    assert report["status"] == "REVIEW_REQUIRED"
