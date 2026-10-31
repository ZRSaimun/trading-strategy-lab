"""Mock-only local broker receipt custody bounds; no API calls or live prices."""
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

import app.trading212_readonly as adapter


def _read(transport):
    return adapter.fetch_trading212_readonly(
        endpoint="instruments", api_key="mock_key", api_secret="mock_secret",
        account_type="INVEST", environment="DEMO", transport=transport,
    )


def test_receipt_window_brackets_mock_callback_and_retains_unattested_flags():
    callback_times = []

    def mock_response(_request):
        callback_times.append(datetime.now(timezone.utc))
        return httpx.Response(
            200, content=b"{}", headers={"content-type": "application/json"}
        )

    result = _read(httpx.MockTransport(mock_response))
    started = datetime.fromisoformat(result["receipt_started_at_utc"])
    completed = datetime.fromisoformat(result["receipt_completed_at_utc"])

    assert started <= callback_times[0] <= completed
    assert result["received_at_utc"] == result["receipt_completed_at_utc"]
    assert result["receipt_elapsed_monotonic_ms"] >= 0
    assert result["receipt_clock_anomaly_detected"] is False
    assert abs(result["receipt_wall_vs_monotonic_delta_ms"]) <= 2000
    assert result["receipt_clock_attested"] is False
    assert result["server_clock_attested"] is False
    assert result["market_data_feed"] is False
    assert result["price_freshness_verified"] is False
    assert result["may_execute_order"] is False


def test_monotonic_elapsed_survives_backwards_wall_clock_adjustment(monkeypatch):
    wall = iter([
        datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 28, 23, 59, tzinfo=timezone.utc),
    ])
    ticks = iter([9_000_000_000, 9_345_678_901])

    class AdjustedClock:
        @staticmethod
        def now(_tz):
            return next(wall)

    monkeypatch.setattr(adapter, "datetime", AdjustedClock)
    # Additional deadline checks sample the same frozen end tick.
    monkeypatch.setattr(adapter, "monotonic_ns", lambda: next(ticks, 9_345_678_901))
    result = _read(httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=b"[]", headers={"content-type": "application/json"}
        )
    ))

    assert result["receipt_started_at_utc"] > result["receipt_completed_at_utc"]
    assert result["receipt_elapsed_monotonic_ms"] == pytest.approx(345.678901)
    assert result["receipt_wall_elapsed_ms"] == -60_000
    assert result["receipt_clock_anomaly_detected"] is True
    assert result["receipt_clock_anomaly_threshold_ms"] == 2000
    assert result["receipt_clock_attested"] is False

@pytest.mark.parametrize("wall_elapsed_ms, expected_anomaly", [
    (200, False),
    (2200, False),  # exactly 2 seconds difference is tolerated
    (2201, True),
    (3_600_000, True),
])
def test_local_clock_consistency_is_only_a_diagnostic(
    monkeypatch, wall_elapsed_ms, expected_anomaly,
):
    start = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    wall = iter([start, start + timedelta(milliseconds=wall_elapsed_ms)])
    ticks = iter([1_000_000_000, 1_200_000_000])

    class MockWallClock:
        @staticmethod
        def now(_tz):
            return next(wall)

    monkeypatch.setattr(adapter, "datetime", MockWallClock)
    # Additional deadline checks sample the same frozen end tick.
    monkeypatch.setattr(adapter, "monotonic_ns", lambda: next(ticks, 1_200_000_000))
    result = _read(httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=b"[]", headers={"content-type": "application/json"}
        )
    ))

    assert result["receipt_elapsed_monotonic_ms"] == 200
    assert result["receipt_wall_elapsed_ms"] == wall_elapsed_ms
    assert result["receipt_wall_vs_monotonic_delta_ms"] == wall_elapsed_ms - 200
    assert result["receipt_clock_anomaly_detected"] is expected_anomaly
    assert result["receipt_clock_attested"] is False
    assert result["server_clock_attested"] is False
    assert result["price_freshness_verified"] is False
    assert result["may_execute_order"] is False


def test_http_date_age_are_unverified_even_when_locally_consistent():
    http_date = format_datetime(datetime.now(timezone.utc), usegmt=True)
    result = _read(httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=b"{}", headers={
                "content-type": "application/json", "Date": http_date, "Age": "12",
            }
        )
    ))
    observation = result["http_time_observation"]
    assert observation["status"] == "AGE_HEADER_INDICATES_CACHE"
    assert observation["http_date_utc"] is not None
    assert observation["http_age_seconds"] == 12
    assert observation["local_clock_disagreement_over_300s"] is False
    assert observation["http_date_attested"] is False
    assert observation["cache_freshness_verified"] is False
    assert observation["may_use_as_market_timestamp"] is False
    assert result["price_freshness_verified"] is False


def test_absent_http_date_does_not_establish_clock_or_cache_freshness():
    result = _read(httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=b"[]", headers={"content-type": "application/json"}
        )
    ))
    observation = result["http_time_observation"]
    assert observation["status"] == "MISSING_DATE_REVIEW_REQUIRED"
    assert observation["http_date_utc"] is None
    assert observation["http_age_seconds"] is None
    assert observation["local_completion_minus_http_date_seconds"] is None
    assert observation["http_date_attested"] is False
    assert observation["may_use_as_market_timestamp"] is False


def test_old_http_date_only_flags_local_clock_disagreement():
    old_date = format_datetime(datetime(2000, 1, 1, tzinfo=timezone.utc), usegmt=True)
    result = _read(httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=b"[]", headers={
                "content-type": "application/json", "Date": old_date, "Age": "0",
            }
        )
    ))
    observation = result["http_time_observation"]
    assert observation["status"] == "LOCAL_CLOCK_DISAGREEMENT_REVIEW_REQUIRED"
    assert observation["local_clock_disagreement_over_300s"] is True
    assert observation["local_completion_minus_http_date_seconds"] > 300
    assert observation["http_date_attested"] is False
    assert result["may_execute_order"] is False


@pytest.mark.parametrize("extra_headers", [
    [("Date", "Thu, 29 Oct 2026 00:00:00 GMT"), ("Date", "Thu, 29 Oct 2026 00:00:00 GMT")],
    [("Date", "not-a-date")],
    [("Date", "Wed, 29 Oct 2026 00:00:00 GMT")],  # wrong weekday
    [("Age", "-1")],
    [("Age", "1,2")],
    [("Age", "1"), ("Age", "2")],
])
def test_ambiguous_or_malformed_http_time_headers_fail_closed(extra_headers):
    headers = [("content-type", "application/json"), *extra_headers]
    with pytest.raises(adapter.ReadOnlyBrokerError, match="broker HTTP time headers"):
        _read(httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"{}", headers=headers)
        ))
