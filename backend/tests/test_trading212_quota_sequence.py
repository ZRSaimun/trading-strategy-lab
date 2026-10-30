"""Offline synthetic receipts only: no broker credentials or HTTP requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.trading212_quota_sequence import (
    QuotaSequenceError, audit_trading212_quota_sequence,
)

BASE = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)


def receipt(second=0, *, used=1, remaining=49, reset=1793034060):
    return {
        "received_at_utc": (BASE + timedelta(seconds=second)).isoformat(),
        "endpoint": "instruments", "environment": "DEMO",
        "account_type_declared": "INVEST", "account_type_verified": False,
        "market_data_feed": False, "may_execute_order": False,
        "rate_limit_observation": {
            "status": "OBSERVED_UNVERIFIED", "limit": 50, "period_seconds": 60,
            "remaining": remaining, "reset_unix_seconds": reset, "used": used,
            "account_quota_verified": False, "safe_to_make_another_request": False,
        },
        "data": {"sensitive": "must-never-leak"},
    }


def audit(rows):
    return audit_trading212_quota_sequence(rows, as_of_utc=(BASE + timedelta(minutes=3)).isoformat())


def test_consistent_same_window_does_not_grant_quota():
    result = audit([receipt(1), receipt(2, used=3, remaining=47)])
    assert result["status"] == "CONSISTENT_UNVERIFIED"
    assert result["same_window_comparison_count"] == 1
    assert result["account_quota_verified"] is False
    assert result["safe_to_make_another_request"] is False
    assert "sensitive" not in str(result)


def test_reversed_counters_are_flagged():
    result = audit([receipt(1, used=3, remaining=47), receipt(2)])
    assert result["issues"]["COUNTERS_REVERSED_WITHIN_WINDOW"] == 1


def test_other_clients_may_consume_more_than_one_credit():
    result = audit([receipt(1), receipt(2, used=49, remaining=1)])
    assert result["status"] == "CONSISTENT_UNVERIFIED"


def test_changed_reset_window_is_not_compared():
    rows = [receipt(1), receipt(65, used=1, remaining=49, reset=1793034120)]
    result = audit(rows)
    assert result["same_window_comparison_count"] == 0
    assert result["window_transition_count"] == 1


def test_backwards_reset_is_reviewed():
    rows = [receipt(1), receipt(2, reset=1793034000)]
    assert audit(rows)["issues"]["RESET_MOVED_BACKWARDS"] == 1


def test_scope_change_disables_comparison():
    rows = [receipt(1), receipt(2)]
    rows[1]["endpoint"] = "exchanges"
    result = audit(rows)
    assert result["same_window_comparison_count"] == 0
    assert result["issues"]["SCOPE_CHANGED"] == 1


def test_nonincreasing_receipt_time_review():
    assert audit([receipt(2), receipt(1)])["issues"]["NONINCREASING_RECEIPT_TIME"] == 1


def test_future_receipt_review():
    assert audit([receipt(200)])["issues"]["RECEIPT_AFTER_AS_OF"] == 1


def test_reset_before_receipt_review():
    assert audit([receipt(70)])["issues"]["RESET_NOT_AFTER_RECEIPT"] == 1


def test_reset_beyond_period_review():
    assert audit([receipt(1, reset=1793034600)])["issues"]["RESET_BEYOND_DECLARED_PERIOD"] == 1


def test_missing_headers_review():
    r = receipt(1)
    r["rate_limit_observation"].update(status="MISSING_REVIEW_REQUIRED", **{
        k: None for k in ("limit", "period_seconds", "remaining", "reset_unix_seconds", "used")})
    assert audit([r])["issues"]["UNVERIFIED_OR_INCOMPLETE_HEADERS"] == 1


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(may_execute_order=True),
    lambda r: r.update(market_data_feed=True),
    lambda r: r.update(account_type_verified=True),
    lambda r: r.update(environment="CFD"),
    lambda r: r.update(endpoint=[]),
    lambda r: r["rate_limit_observation"].update(status=[]),
    lambda r: r.update(received_at_utc="2026-10-26T17:00:00+01:00"),
    lambda r: r.update(received_at_utc="not-a-date"),
    lambda r: r["rate_limit_observation"].update(account_quota_verified=True),
    lambda r: r["rate_limit_observation"].update(safe_to_make_another_request=True),
    lambda r: r["rate_limit_observation"].update(used=True),
    lambda r: r["rate_limit_observation"].update(used=-1),
    lambda r: r["rate_limit_observation"].update(used=99),
    lambda r: r["rate_limit_observation"].update(status="MISSING_REVIEW_REQUIRED"),
])
def test_invalid_input_fail_closed_and_sanitized(mutate):
    r = receipt(1)
    mutate(r)
    with pytest.raises(QuotaSequenceError) as exc:
        audit([r])
    assert "sensitive" not in str(exc.value)


def test_empty_and_unbounded_rejected():
    for rows in ([], [receipt(1)] * 501, "not-a-list"):
        with pytest.raises(QuotaSequenceError):
            audit(rows)


def test_bad_as_of_rejected():
    with pytest.raises(QuotaSequenceError):
        audit_trading212_quota_sequence([receipt(1)], as_of_utc="2026-10-26")


def test_does_not_mutate_inputs():
    rows = [receipt(1), receipt(2)]
    original = deepcopy(rows)
    audit(rows)
    assert rows == original
