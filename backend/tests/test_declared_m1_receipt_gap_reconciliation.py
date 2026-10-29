"""Synthetic receipt-to-session gap cross-audit; no network or real prices."""
from dataclasses import replace

import pytest

from app.declared_m1_receipt_gap_reconciliation import (
    audit_declared_m1_receipt_gap_reconciliation,
)
from app.expected_bar_manifest import compile_expected_m1_manifest

T = 1790000040


def manifest(**updates):
    values = dict(
        provider="fixture", symbol="XAU/USD", venue="synthetic",
        price_side="BID", calendar_id="fixture", calendar_revision="r1",
        calendar_source="operator fixture", observed_at_utc=T + 320,
        sessions_utc=[(T, T + 120), (T + 180, T + 300)],
        exclusions_utc=[(T + 60, T + 120)],
    )
    return compile_expected_m1_manifest(**(values | updates))


def bar(t, **changes):
    row = dict(
        provider="fixture", symbol="XAU/USD", venue="synthetic",
        price_side="BID", bar_start_utc=t, received_at_utc=t + 65,
        open=100., high=102., low=99., close=101.,
    )
    row.update(changes)
    return row


def audit(rows, **limits):
    return audit_declared_m1_receipt_gap_reconciliation(rows, manifest(), **limits)


def test_complete_reconciled_still_unverified_and_not_forecast_ready():
    report = audit([bar(T), bar(T + 180), bar(T + 240)])
    assert report["status"] == "DECLARED_RECONCILED_UNVERIFIED"
    assert report["missing_expected_minutes"] == 0
    assert report["missing_gap_runs"] == 0
    assert report["receipt_census"]["expected_minutes"] == 3
    assert report["session_gap_audit"]["expected_minutes"] == 3
    assert report["source_authenticated"] is False
    assert report["forecast_ready"] is False
    assert report["live"] is False and report["may_execute_order"] is False


def test_session_break_and_exclusion_do_not_create_missing_runs():
    report = audit([bar(T)])
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["missing_expected_minutes"] == 2
    assert report["missing_gap_runs"] == 1
    assert report["trailing_missing_expected_minutes"] == 2
    assert [r["missing_expected_minutes"] for r in report["declared_session_coverage"]] == [0, 2]


def test_closure_observation_does_not_satisfy_expected_gap():
    report = audit([bar(T), bar(T + 60), bar(T + 240)])
    assert report["missing_expected_minutes"] == 1
    assert report["unexpected_unique_minutes"] == 1
    assert report["session_gap_audit"]["observed_in_declared_exclusions_unique_minutes"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_backward_receipt_bar_order_requires_review_despite_full_coverage():
    report = audit([bar(T + 180), bar(T), bar(T + 240)])
    assert report["receipt_census"]["status"] == "INTERNAL_CENSUS_ONLY_NOT_LIVE"
    assert report["backward_timestamp_transitions"] == 1
    assert report["missing_expected_minutes"] == 0
    assert report["status"] == "REVIEW_REQUIRED"


def test_duplicates_and_revisions_never_silently_pass():
    report = audit([bar(T), bar(T), bar(T + 180), bar(T + 240)])
    assert report["duplicate_receipt_rows"] == 1
    assert report["status"] == "REVIEW_REQUIRED"
    revised = audit([bar(T), bar(T, close=100.5), bar(T + 180), bar(T + 240)])
    assert revised["receipt_census"]["conflicting_duplicate_rows"] == 1
    assert revised["status"] == "REVIEW_REQUIRED"


def test_stale_or_late_receipts_fail_even_when_gap_population_complete():
    report = audit([bar(T), bar(T + 180), bar(T + 240)], max_receipt_lag_seconds=0)
    assert report["missing_expected_minutes"] == 0
    assert report["receipt_census"]["late_receipt_rows"] == 3
    assert report["status"] == "REVIEW_REQUIRED"


def test_empty_receipts_are_missing_and_never_green():
    report = audit([])
    assert report["missing_expected_minutes"] == 3
    assert report["trailing_missing_expected_minutes"] == 3
    assert report["status"] == "REVIEW_REQUIRED"


def test_zero_samples_preserve_counts():
    report = audit([bar(T + 60)], sample_limit=0)
    assert report["missing_expected_minutes"] == 3
    assert report["session_gap_audit"]["missing_gap_samples"] == []
    assert report["receipt_census"]["missing_utc_samples"] == []


def test_rejects_mutated_manifest_mixed_identity_and_invalid_receipt():
    m = manifest()
    with pytest.raises(ValueError):
        audit_declared_m1_receipt_gap_reconciliation(
            [bar(T)], replace(m, expected_minutes=(T,)))
    with pytest.raises(ValueError):
        audit([bar(T, price_side="ASK")])
    with pytest.raises(ValueError):
        audit([bar(T, received_at_utc=T + 30)])
    with pytest.raises(ValueError):
        audit([bar(T, verified=True)])


@pytest.mark.parametrize("bad", [True, -1, 51, "5"])
def test_invalid_sample_limit_rejected(bad):
    with pytest.raises(ValueError):
        audit([bar(T)], sample_limit=bad)


def test_report_excludes_raw_prices():
    report = audit([bar(T)])
    assert "open" not in report and "close" not in report
    assert "100.0" not in str(report)
