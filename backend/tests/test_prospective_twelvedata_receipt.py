"""Synthetic, zero-network one-shot provider observation tests."""
import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.expected_bar_manifest import compile_expected_m1_manifest
import app.prospective_twelvedata_receipt as adapter

T = 1790000040
NOW = T + 180


def manifest(**changes):
    base = dict(
        provider="twelvedata", symbol="XAU/USD", venue="UNVERIFIED",
        price_side="UNSPECIFIED", calendar_id="test-only",
        calendar_revision="fixture-r1", calendar_source="operator fixture",
        observed_at_utc=NOW, sessions_utc=[(T, T + 120)], exclusions_utc=[],
    )
    return compile_expected_m1_manifest(**(base | changes))


def rows(*times):
    return [dict(time=t, open=100., high=102., low=99., close=101., volume=None)
            for t in times]


def snapshot(candles):
    return json.dumps({
        "meta": {"symbol": "XAU/USD", "interval": "1min", "exchange_timezone": "UTC"},
        "values": [dict(time=datetime.fromtimestamp(r["time"], timezone.utc).isoformat(),
                        open="100", high="102", low="99", close="101") for r in candles],
    }, separators=(",", ":")).encode()


def fixture(monkeypatch, *, candles=None, raw=None, now=NOW, wire=None):
    observed = []
    if candles is None:
        candles = rows(T, T + 60)
    if raw is None:
        raw = snapshot(candles)

    if wire is None:
        provider_body = b'{"status":"ok","meta":{"symbol":"XAU/USD"}}'
        wire = {
            "decoded_http_body_sha256": hashlib.sha256(provider_body).hexdigest(),
            "decoded_http_body_bytes": len(provider_body),
            "normalized_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
            "http_status": 200,
        }

    async def fake_retrieve(key, instrument, limit, end, started, *, include_wire_evidence=False):
        assert include_wire_evidence is True
        observed.append((key, instrument, limit, end, started))
        return candles, raw, wire

    monkeypatch.setattr(adapter, "retrieve", fake_retrieve)
    monkeypatch.setattr(adapter, "_wall_clock", lambda: now)
    monkeypatch.setattr(adapter, "_monotonic", lambda: 100.0)
    return observed


def run(m=None, **kwargs):
    return asyncio.run(adapter.review_twelvedata_completed_m1(
        api_key="test-only-key", manifest=m or manifest(), **kwargs))


def test_complete_observation_server_stamped_and_still_not_live(monkeypatch):
    calls = fixture(monkeypatch)
    report = run()
    assert calls == [("test-only-key", "XAUUSD-TD", 2, T + 60, NOW)]
    assert report["status"] == "INTERNAL_CENSUS_ONLY_NOT_LIVE"
    assert report["missing_expected_minutes"] == 0
    assert report["server_response_received_at_utc"] == NOW
    assert report["server_receipt_time_observed"] is True
    assert report["source_snapshot_sha256"] == hashlib.sha256(snapshot(rows(T, T+60))).hexdigest()
    assert report["decoded_http_body_sha256"] != report["source_snapshot_sha256"]
    assert report["decoded_http_body_bytes"] > 0
    assert report["http_body_hash_semantics"] == "httpx-decoded-response-body-not-TLS-wire"
    assert report["source_authenticated"] is False
    assert report["expected_calendar_verified"] is False
    assert report["provider_entitlement_verified"] is False
    assert report["executable_bid_ask_verified"] is False
    assert report["live"] is False and report["may_execute_order"] is False
    assert "test-only-key" not in str(report)


def test_missing_completed_minute_requires_review(monkeypatch):
    fixture(monkeypatch, candles=rows(T))
    report = run()
    assert report["missing_expected_minutes"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_unexpected_minute_requires_review(monkeypatch):
    fixture(monkeypatch, candles=rows(T, T+60, T-60))
    report = run()
    assert report["unexpected_observed_minutes"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_replayed_old_bars_cannot_appear_fresh(monkeypatch):
    fixture(monkeypatch, now=NOW+300)
    report = run()
    assert report["stale_expected_candle"] is True
    assert report["late_receipt_rows"] > 0
    assert report["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("changes", [
    {"symbol": "NQ"}, {"provider": "not-twelvedata"},
    {"venue": "NYSE"}, {"price_side": "BID"},
])
def test_identity_mismatch_rejected_without_vendor_call(monkeypatch, changes):
    calls = fixture(monkeypatch)
    with pytest.raises(adapter.ProspectiveReceiptError):
        run(manifest(**changes))
    assert calls == []


def test_mutated_manifest_rejected_before_request(monkeypatch):
    calls = fixture(monkeypatch)
    with pytest.raises(adapter.ProspectiveReceiptError):
        run(replace(manifest(), manifest_sha256="0"*64))
    assert calls == []


def test_future_calendar_rejected_before_request(monkeypatch):
    calls = fixture(monkeypatch)
    m = manifest(observed_at_utc=NOW+120, sessions_utc=[(T, T+240)])
    with pytest.raises(adapter.ProspectiveReceiptError):
        run(m)
    assert calls == []


def test_invalid_key_rejected_before_request(monkeypatch):
    calls = fixture(monkeypatch)
    with pytest.raises(adapter.ProspectiveReceiptError):
        asyncio.run(adapter.review_twelvedata_completed_m1(api_key="bad\nkey", manifest=manifest()))
    assert calls == []


def test_snapshot_tampering_rejected_and_sanitized(monkeypatch):
    fixture(monkeypatch, raw=b'{"meta":{},"values":[]}')
    with pytest.raises(adapter.ProspectiveReceiptError, match="Provider receipt rejected") as exc:
        run()
    assert "test-only-key" not in str(exc.value)


def test_response_clock_regression_rejected(monkeypatch):
    calls = fixture(monkeypatch)
    ticks = iter((NOW, NOW-1))
    monkeypatch.setattr(adapter, "_wall_clock", lambda: next(ticks))
    with pytest.raises(adapter.ProspectiveReceiptError, match="Provider receipt rejected"):
        run()
    assert len(calls) == 1


def test_duplicate_observations_rejected_by_census(monkeypatch):
    fixture(monkeypatch, candles=rows(T, T, T+60))
    report = run()
    assert report["duplicate_receipt_rows"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_too_many_expected_minutes_rejected_without_request(monkeypatch):
    calls = fixture(monkeypatch, now=T+5001*60+60)
    m = manifest(observed_at_utc=T+5001*60+60,
                 sessions_utc=[(T, T+5001*60)])
    with pytest.raises(adapter.ProspectiveReceiptError):
        run(m)
    assert calls == []


def test_provider_failure_is_sanitized(monkeypatch):
    calls = fixture(monkeypatch)
    async def fail(*args):
        raise adapter.ProviderError("secret upstream payload")
    monkeypatch.setattr(adapter, "retrieve", fail)
    with pytest.raises(adapter.ProspectiveReceiptError, match="Provider receipt rejected") as exc:
        run()
    assert "secret upstream payload" not in str(exc.value)
    assert calls == []


@pytest.mark.parametrize("bad_wire", [
    {},
    {"decoded_http_body_sha256": "not-a-hash"},
    {"decoded_http_body_sha256": "f"*64, "decoded_http_body_bytes": True,
     "normalized_snapshot_sha256": "f"*64, "http_status": 200},
    {"decoded_http_body_sha256": "f"*64, "decoded_http_body_bytes": 3_000_001,
     "normalized_snapshot_sha256": "f"*64, "http_status": 200},
    {"decoded_http_body_sha256": "f"*64, "decoded_http_body_bytes": 20,
     "normalized_snapshot_sha256": "0"*64, "http_status": 200},
    {"decoded_http_body_sha256": "f"*64, "decoded_http_body_bytes": 20,
     "normalized_snapshot_sha256": "f"*64, "http_status": 302},
])
def test_invalid_or_unbound_wire_receipt_is_rejected(monkeypatch, bad_wire):
    fixture(monkeypatch, wire=bad_wire)
    with pytest.raises(adapter.ProspectiveReceiptError, match="Provider receipt rejected"):
        run()
