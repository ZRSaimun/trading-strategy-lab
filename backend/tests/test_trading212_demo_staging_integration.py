"""Mock-transport integration: real SQLite reservation -> real read-only GET."""
import json
import os
import sqlite3

import httpx
import pytest

from app import trading212_request_budget as budget
from app.trading212_demo_staging_probe import probe_trading212_demo_metadata
from app.trading212_readonly import ReadOnlyBrokerError


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    os.chmod(private, 0o700)
    db = str(private / "requests.sqlite")
    monkeypatch.setattr(budget.time, "time", lambda: 1793037600)
    budget.provision_trading212_read_budget(
        db, account_scope_sha256="a" * 64, environment="DEMO",
        account_type="INVEST", utc_day="2026-10-26", max_requests=2,
        rights_evidence_sha256="b" * 64,
        entitlement_evidence_sha256="c" * 64,
        owner_confirmed=True,
    )
    return db


def _call(ledger, transport, request_id="1" * 32):
    return probe_trading212_demo_metadata(
        owner_confirmed=True, db_path=ledger, request_id=request_id,
        account_scope_sha256="a" * 64, endpoint="instruments",
        account_type="INVEST", api_key="synthetic_key",
        api_secret="synthetic_secret", transport=transport,
    )


def _count(ledger):
    with sqlite3.connect(ledger) as conn:
        return conn.execute("SELECT COUNT(*) FROM request_reservation").fetchone()[0]


def test_real_budget_and_mock_get_return_redacted_receipt(ledger):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        assert request.method == "GET"
        return httpx.Response(200, json=[{"ticker": "SENSITIVE_TEST_TICKER", "currencyCode": "USD",
             "type": "STOCK", "workingScheduleId": 1,
             "maxOpenQuantity": 10.0, "extendedHours": False,
             "name": "Sensitive Test", "shortName": "Sensitive"}], headers={
            "x-ratelimit-limit": "50", "x-ratelimit-period": "60",
            "x-ratelimit-remaining": "49", "x-ratelimit-used": "1",
            "x-ratelimit-reset": "1793037660",
        })
    transport = httpx.MockTransport(handler)
    out = _call(ledger, transport)
    assert calls == ["https://demo.trading212.com/api/v0/equity/metadata/instruments"]
    assert _count(ledger) == 1
    assert out["status"] == "DEMO_METADATA_OBSERVED_UNVERIFIED"
    assert out["rate_limit_status"] == "OBSERVED_UNVERIFIED"
    assert out["market_data_feed"] is False and out["may_execute_order"] is False
    text = json.dumps(out)
    for secret in ("synthetic_key", "synthetic_secret", "SENSITIVE_TEST_TICKER", "a" * 64):
        assert secret not in text
    with pytest.raises(budget.BrokerBudgetError):
        _call(ledger, transport)
    assert len(calls) == 1 and _count(ledger) == 1


def test_failed_mock_get_consumes_reservation_without_retry(ledger):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(429, text="synthetic_secret private body")
    with pytest.raises(ReadOnlyBrokerError) as error:
        _call(ledger, httpx.MockTransport(handler))
    assert "synthetic_secret" not in str(error.value)
    assert calls == ["GET"] and _count(ledger) == 1
