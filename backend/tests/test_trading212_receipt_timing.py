"""Mock-only local broker receipt custody bounds; no API calls or live prices."""
from datetime import datetime, timezone

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
    monkeypatch.setattr(adapter, "monotonic_ns", lambda: next(ticks))
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
    monkeypatch.setattr(adapter, "monotonic_ns", lambda: next(ticks))
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
