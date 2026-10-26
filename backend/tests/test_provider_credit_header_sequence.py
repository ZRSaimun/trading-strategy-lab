"""Synthetic-only quota header consistency checks; no vendor calls."""
from datetime import datetime, timezone

import pytest
from app.provider_credit_header_sequence import (
    CreditHeaderSequenceError, audit_twelvedata_credit_header_sequence,
)

T = int(datetime(2026, 10, 26, 8, tzinfo=timezone.utc).timestamp())


def receipt(i, *, used=None, left=None, stamp=None):
    if stamp is None:
        stamp = T + i * 60
    return {
        "credit_budget_reservation_id": f"{i:032x}",
        "server_request_started_at_utc": stamp,
        "server_response_received_at_utc": stamp + 1,
        "protocol": "one-shot-twelvedata-m1-observation-v1",
        "source_endpoint": "https://api.twelvedata.com/time_series",
        "instrument_mapping": "XAUUSD-TD -> XAU/USD",
        "provider_http_status": 200,
        "provider_credit_header_status": "OBSERVED_UNVERIFIED",
        "provider_api_credits_used": i + 1 if used is None else used,
        "provider_api_credits_left": 799 - i if left is None else left,
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


def audit(reports, **kwargs):
    return audit_twelvedata_credit_header_sequence(
        reports, declared_window_start_utc=kwargs.get("start", T),
        declared_window_end_utc=kwargs.get("end", T + 600))


def test_consistent_sorted_or_reversed_is_only_self_attested():
    for reports in ([receipt(0), receipt(1)], [receipt(1), receipt(0)]):
        result = audit(reports)
        assert result["status"] == "SELF_ATTESTED_SEQUENCE_ONLY"
        assert result["compared_adjacent_pairs"] == 1
        assert result["provider_account_credit_usage_reconciled"] is False
        assert result["receipt_population_complete"] is False
        assert result["source_authenticated"] is False
        assert result["may_execute_order"] is False
        assert "00000000000000000000000000000000" not in str(result)


@pytest.mark.parametrize("reports,field", [
    ([receipt(0), receipt(1, used=1, left=799)], "unexplained_credit_deltas"),
    ([receipt(0), receipt(1, used=3, left=797)], "unexplained_credit_deltas"),
    ([receipt(0), receipt(1, used=2, left=900)], "contradictory_counter_pairs"),
    ([receipt(0), receipt(1, used=2, left=700)], "contradictory_counter_pairs"),
])
def test_anomalies_review_only(reports, field):
    result = audit(reports)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result[field] == 1


def test_missing_headers_never_imply_complete():
    x = receipt(0)
    x.update(provider_credit_header_status="MISSING_REVIEW_REQUIRED",
             provider_api_credits_used=None, provider_api_credits_left=None)
    result = audit([x, receipt(1)])
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["reports_missing_credit_headers"] == 1
    assert result["compared_adjacent_pairs"] == 0


def test_tied_response_times_are_ambiguous():
    result = audit([receipt(0), receipt(1, stamp=T)])
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["ambiguous_response_timestamp_pairs"] == 1


def test_empty_and_single_report_not_accepted_as_reconciled():
    for reports in ([], [receipt(0)]):
        assert audit(reports)["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(credit_budget_reservation_id="bad"),
    lambda r: r.update(server_request_started_at_utc=True),
    lambda r: r.update(server_response_received_at_utc=T + 1000),
    lambda r: r.update(provider_http_status=True),
    lambda r: r.update(source_authenticated=True),
    lambda r: r.update(provider_account_credit_usage_reconciled=True),
    lambda r: r.update(may_execute_order=True),
    lambda r: r.update(provider_credit_header_status="VERIFIED"),
    lambda r: r.update(provider_api_credits_used=0),
    lambda r: r.update(provider_api_credits_used=True),
    lambda r: r.update(provider_api_credits_left=-1),
    lambda r: r.update(instrument_mapping="CFD"),
    lambda r: r.update(source_endpoint="https://example.invalid"),
    lambda r: r.update(protocol="live"),
])
def test_malformed_or_forged_reports_denied(mutate):
    x = receipt(0)
    mutate(x)
    with pytest.raises(CreditHeaderSequenceError):
        audit([x])


def test_duplicate_id_denied():
    with pytest.raises(CreditHeaderSequenceError):
        audit([receipt(0), receipt(0)])


@pytest.mark.parametrize("start,end", [
    (T, T), (T, T + 90000), (True, T + 600),
    (T, True), (T, T + 999999999), (0, T + 600),
])
def test_bad_declared_window_denied(start, end):
    with pytest.raises(CreditHeaderSequenceError):
        audit([], start=start, end=end)


def test_bounded_and_wrong_type_denied():
    for reports in (None, {}, [receipt(0)] * 5001):
        with pytest.raises(CreditHeaderSequenceError):
            audit(reports)


def test_missing_header_pair_with_counter_denied():
    x = receipt(0)
    x["provider_credit_header_status"] = "MISSING_REVIEW_REQUIRED"
    with pytest.raises(CreditHeaderSequenceError):
        audit([x])
