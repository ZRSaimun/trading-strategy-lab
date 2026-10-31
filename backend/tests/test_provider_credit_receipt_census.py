"""Synthetic offline reservation/receipt coverage tests; never contacts vendor."""
from datetime import datetime, timezone
import sqlite3

import pytest

from app.provider_credit_receipt_census import (
    CreditReceiptCensusError, audit_twelvedata_credit_receipt_coverage,
)

DAY = "2026-10-26"
STAMP = int(datetime(2026, 10, 26, 8, tzinfo=timezone.utc).timestamp())
SCHEMA = """
CREATE TABLE daily_policy (
 utc_day TEXT PRIMARY KEY, provider TEXT NOT NULL CHECK(provider='twelvedata'),
 symbol TEXT NOT NULL CHECK(symbol='XAU/USD'),
 purpose TEXT NOT NULL CHECK(purpose='completed-m1-review'),
 max_credits INTEGER NOT NULL CHECK(max_credits BETWEEN 1 AND 5000),
 entitlement_evidence_sha256 TEXT NOT NULL,
 rights_evidence_sha256 TEXT NOT NULL
);
CREATE TABLE credit_reservation (
 request_id TEXT PRIMARY KEY, utc_day TEXT NOT NULL REFERENCES daily_policy(utc_day),
 manifest_sha256 TEXT NOT NULL, reserved_at_utc INTEGER NOT NULL,
 cost INTEGER NOT NULL CHECK(cost=1)
);
"""


def ledger(tmp_path, n=2):
    path = tmp_path / "credits.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO daily_policy VALUES (?,?,?,?,?,?,?)",
                   (DAY, "twelvedata", "XAU/USD", "completed-m1-review", 5,
                    "a"*64, "b"*64))
        for i in range(n):
            db.execute("INSERT INTO credit_reservation VALUES (?,?,?,?,1)",
                       (f"{i:032x}", DAY, "c"*64, STAMP+i*60))
    path.chmod(0o600)
    return path


def receipt(i=0, status="OBSERVED_UNVERIFIED"):
    return {
        "credit_budget_reservation_id": f"{i:032x}",
        "credit_budget_utc_day": DAY,
        "operator_manifest_sha256": "c"*64,
        "decoded_http_body_sha256": "d"*64,
        "source_snapshot_sha256": "e"*64,
        "server_request_started_at_utc": STAMP+i*60,
        "server_response_received_at_utc": STAMP+i*60+1,
        "server_request_elapsed_ms": 1000,
        "protocol": "one-shot-twelvedata-m1-observation-v1",
        "source_endpoint": "https://api.twelvedata.com/time_series",
        "instrument_mapping": "XAUUSD-TD -> XAU/USD",
        "provider_http_status": 200,
        "provider_credit_header_status": status,
        "provider_api_credits_used": 1 if status == "OBSERVED_UNVERIFIED" else None,
        "provider_api_credits_left": 799 if status == "OBSERVED_UNVERIFIED" else None,
        "provider_credit_quota_window_verified": False,
        "provider_account_credit_usage_reconciled": False,
        "source_authenticated": False,
        "provider_entitlement_verified": False,
        "retention_and_display_rights_verified": False,
        "expected_calendar_verified": False,
        "executable_bid_ask_verified": False,
        "live": False,
        "may_execute_order": False,
    }


def census(path, reports, day=DAY):
    return audit_twelvedata_credit_receipt_coverage(
        str(path), utc_day=day, receipt_reports=reports)


def test_complete_coverage_read_only_and_no_identifiers(tmp_path):
    path = ledger(tmp_path)
    original = path.read_bytes()
    report = census(path, [receipt(0), receipt(1)])
    assert report["status"] == "LOCAL_COVERAGE_ONLY"
    assert report["audited_reservations"] == 2
    assert report["matched_receipt_reports"] == 2
    assert report["reservations_without_receipt"] == 0
    assert report["observed_credit_header_pairs"] == 2
    assert report["provider_account_credit_usage_reconciled"] is False
    assert report["may_execute_order"] is False
    assert f"{0:032x}" not in str(report)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("credits.sqlite-*"))


def test_missing_receipt_is_uncertain_not_refunded(tmp_path):
    report = census(ledger(tmp_path), [receipt(0)])
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["reservations_without_receipt"] == 1


def test_missing_credit_headers_review_required(tmp_path):
    report = census(ledger(tmp_path), [receipt(0, "MISSING_REVIEW_REQUIRED"), receipt(1)])
    assert report["reports_missing_credit_headers"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_zero_reservations_is_local_only_not_account_proof(tmp_path):
    report = census(ledger(tmp_path, n=0), [])
    assert report["status"] == "LOCAL_COVERAGE_ONLY"
    assert report["provider_entitlement_verified"] is False


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(credit_budget_reservation_id="f"*32),
    lambda r: r.update(credit_budget_utc_day="2026-10-25"),
    lambda r: r.update(operator_manifest_sha256="0"*64),
    lambda r: r.update(decoded_http_body_sha256="bad"),
    lambda r: r.update(source_snapshot_sha256="bad"),
    lambda r: r.update(server_request_started_at_utc=STAMP-1),
    lambda r: r.update(server_response_received_at_utc=STAMP+100),
    lambda r: r.update(server_request_elapsed_ms=True),
    lambda r: r.update(provider_http_status=True),
    lambda r: r.update(protocol="live-v1"),
    lambda r: r.update(source_endpoint="https://other.invalid"),
    lambda r: r.update(instrument_mapping="XAU/USD BID"),
    lambda r: r.update(source_authenticated=True),
    lambda r: r.update(live=True),
    lambda r: r.update(may_execute_order=True),
    lambda r: r.update(provider_credit_quota_window_verified=True),
    lambda r: r.update(provider_account_credit_usage_reconciled=True),
    lambda r: r.update(provider_credit_header_status="VERIFIED"),
    lambda r: r.update(provider_api_credits_used=0),
    lambda r: r.update(provider_api_credits_left=-1),
    lambda r: r.update(provider_api_credits_used="1"),
])
def test_malformed_or_unverified_receipt_denied(tmp_path, mutation):
    path = ledger(tmp_path, n=1)
    r = receipt()
    mutation(r)
    with pytest.raises(CreditReceiptCensusError):
        census(path, [r])


def test_duplicate_receipt_denied(tmp_path):
    with pytest.raises(CreditReceiptCensusError, match="Duplicate"):
        census(ledger(tmp_path), [receipt(0), receipt(0)])


def test_bounded_reports_and_invalid_day_denied(tmp_path):
    path = ledger(tmp_path)
    for reports in (None, {}, [receipt(0)]*5001):
        with pytest.raises(CreditReceiptCensusError):
            census(path, reports)
    for day in ("2026-02-30", "2026-10-26T00:00", None):
        with pytest.raises(CreditReceiptCensusError):
            census(path, [], day)


def test_missing_policy_denied(tmp_path):
    with pytest.raises(CreditReceiptCensusError, match="No audited"):
        census(ledger(tmp_path), [], "2026-10-25")


def test_corrupt_ledger_denied(tmp_path):
    path = ledger(tmp_path)
    path.write_bytes(b"bad SQLite")
    with pytest.raises(CreditReceiptCensusError):
        census(path, [])


def test_public_ledger_denied(tmp_path):
    path = ledger(tmp_path)
    path.chmod(0o644)
    with pytest.raises(CreditReceiptCensusError):
        census(path, [])
