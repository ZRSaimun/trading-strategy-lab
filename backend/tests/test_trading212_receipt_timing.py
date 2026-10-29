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
    assert result["receipt_clock_attested"] is False
