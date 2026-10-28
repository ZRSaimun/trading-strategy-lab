"""Synthetic-only tests: no network, accounts, prices or real provider receipts."""
from copy import deepcopy

import pytest

from app.declared_completed_m1_receipts import audit_declared_completed_m1_receipts

T = 1_790_000_100
assert T % 60 == 0


def row(start=T, *, event="e1", received=None):
    return dict(
        event_id=event, provider="synthetic", instrument="XAU/USD",
        source_id="test:feed", price_side="mid", minute_start_utc=start,
        finalized_at_utc=start + 61,
        received_at_utc=start + 62 if received is None else received,
        is_final=True, open="100.00", high="101.00", low="99.00", close="100.50",
    )


def audit(rows, **kw):
    return audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", as_of_utc=T + 240, **kw
    )


def test_one_completed_receipt_is_never_authenticated_or_live():
    report = audit([row()])
    assert report["structurally_clean"] is True
    assert report["declared_freshness_within_budget"] is True
    assert report["latest_candle_end_age_seconds"] == 180
    assert report["market_data_live"] is False
    assert report["research_ready"] is False
    assert report["may_execute_order"] is False
    assert report["licensing_verified"] is False


def test_digest_is_deterministic_and_input_unchanged():
    rows = [row()]
    original = deepcopy(rows)
    assert audit(rows) == audit(rows)
    assert rows == original
    altered = deepcopy(rows)
    altered[0]["close"] = "100.51"
    assert audit(rows)["receipt_inventory_sha256"] != audit(altered)["receipt_inventory_sha256"]


def test_gap_is_observation_not_calendar_proof():
    report = audit([row(T, event="e1"), row(T + 120, event="e2", received=T + 182)])
    assert report["observed_gap_minutes_not_proven_missing"] == 1
    assert report["structurally_clean"] is True
    assert report["session_calendar_verified"] is False


def test_declared_expected_inventory_detects_missing_and_extra():
    report = audit([row()], expected_utc_minutes=[T, T + 60])
    assert report["missing_declared_expected_minutes"] == 1
    assert report["extra_minutes_outside_declared_expected"] == 0
    assert report["structurally_clean"] is False
    report2 = audit([row()], expected_utc_minutes=[T + 60])
    assert report2["extra_minutes_outside_declared_expected"] == 1


def test_duplicate_minute_is_quarantined_even_if_ohlc_equal():
    report = audit([row(event="e1"), row(event="e2", received=T + 63)])
    assert report["duplicate_minute_rows"] == 1
    assert report["structurally_clean"] is False


def test_backward_minute_is_quarantined():
    report = audit([row(T + 60, event="e1", received=T + 123),
                    row(T, event="e2", received=T + 124)])
    assert report["backward_candle_events"] == 1
    assert report["structurally_clean"] is False


def test_transport_lag_and_stale_candle_are_separate():
    late = row(received=T + 120)
    report = audit([late], max_transport_lag_seconds=30)
    assert report["transport_lag_exceeded_rows"] == 1
    assert report["declared_freshness_within_budget"] is False
    assert audit([row()], max_age_seconds=179)["declared_freshness_within_budget"] is False


@pytest.mark.parametrize("field,value", [
    ("event_id", "bad\\n"), ("provider", "other"), ("instrument", "EUR/USD"),
    ("source_id", "other"), ("price_side", "bid"), ("is_final", False),
    ("is_final", 1), ("minute_start_utc", T + 1),
    ("minute_start_utc", True), ("finalized_at_utc", T + 59),
    ("received_at_utc", T + 60), ("received_at_utc", T + 241),
    ("open", "NaN"), ("high", "Infinity"), ("low", "-1"),
    ("close", "1e10"), ("high", "99"), ("low", "102"),
])
def test_malformed_or_mixed_receipts_fail_closed(field, value):
    bad = row()
    bad[field] = value
    with pytest.raises(ValueError):
        audit([bad])


def test_duplicate_event_id_rejected():
    with pytest.raises(ValueError, match="Duplicate source event"):
        audit([row(), row(received=T + 63)])


def test_receipt_clock_regression_rejected():
    with pytest.raises(ValueError, match="ingestion timestamps"):
        audit([row(event="e1", received=T + 200),
               row(T + 60, event="e2", received=T + 123)])


@pytest.mark.parametrize("expected", [[T, T], [T + 1], [T + 60, T], [True]])
def test_bad_expected_inventory_rejected(expected):
    with pytest.raises(ValueError):
        audit([row()], expected_utc_minutes=expected)


@pytest.mark.parametrize("kwargs", [
    {"max_age_seconds": True}, {"max_age_seconds": 3601},
    {"max_transport_lag_seconds": -1}, {"max_transport_lag_seconds": 301},
])
def test_unsafe_budgets_rejected(kwargs):
    with pytest.raises(ValueError):
        audit([row()], **kwargs)


def test_extra_keys_and_empty_inventory_rejected():
    with pytest.raises(ValueError):
        audit([])
    bad = row()
    bad["license_verified"] = True
    with pytest.raises(ValueError):
        audit([bad])


def test_delayed_finalization_cannot_hide_behind_fast_transport():
    late = row()
    late["finalized_at_utc"] = T + 180
    late["received_at_utc"] = T + 181
    report = audit([late], max_finalization_lag_seconds=60)
    assert report["transport_lag_exceeded_rows"] == 0
    assert report["finalization_lag_exceeded_rows"] == 1
    assert report["structurally_clean"] is False
    assert report["declared_freshness_within_budget"] is False
    assert report["market_data_live"] is False
    assert report["may_execute_order"] is False


def test_finalization_lag_exact_budget_is_inclusive():
    item = row()
    item["finalized_at_utc"] = T + 120
    item["received_at_utc"] = T + 121
    report = audit([item], max_finalization_lag_seconds=60)
    assert report["finalization_lag_exceeded_rows"] == 0
    assert report["structurally_clean"] is True
    assert report["declared_max_finalization_lag_seconds"] == 60


def test_finalization_lag_is_checked_for_old_rows_not_only_newest():
    old = row(event="old")
    old["finalized_at_utc"] = T + 180
    old["received_at_utc"] = T + 181
    fresh = row(T + 60, event="fresh", received=T + 183)
    report = audit([old, fresh], max_finalization_lag_seconds=60)
    assert report["latest_candle_end_age_seconds"] == 120
    assert report["finalization_lag_exceeded_rows"] == 1
    assert report["declared_freshness_within_budget"] is False


@pytest.mark.parametrize("bad_budget", [-1, 301, True, 1.0, "60"])
def test_finalization_budget_must_be_bounded_integer(bad_budget):
    with pytest.raises(ValueError, match="Bounded freshness"):
        audit([row()], max_finalization_lag_seconds=bad_budget)


def test_audit_policy_fingerprint_is_deterministic_and_separate_from_receipts():
    rows = [row()]
    before = deepcopy(rows)
    first = audit(rows, expected_utc_minutes=[T])
    second = audit(rows, expected_utc_minutes=[T])
    assert first["declared_audit_policy_sha256"] == second["declared_audit_policy_sha256"]
    assert len(first["declared_audit_policy_sha256"]) == 64
    assert rows == before
    assert first["source_authenticity_verified"] is False
    assert first["may_execute_order"] is False


def test_expected_inventory_changes_policy_not_receipt_fingerprint():
    rows = [row()]
    one = audit(rows, expected_utc_minutes=[T])
    two = audit(rows, expected_utc_minutes=[T, T + 60])
    assert one["receipt_inventory_sha256"] == two["receipt_inventory_sha256"]
    assert one["declared_audit_policy_sha256"] != two["declared_audit_policy_sha256"]
    assert one["structurally_clean"] is True
    assert two["structurally_clean"] is False


def test_absent_and_explicitly_empty_expected_inventory_are_distinct():
    rows = [row()]
    absent = audit(rows)
    empty = audit(rows, expected_utc_minutes=[])
    assert absent["receipt_inventory_sha256"] == empty["receipt_inventory_sha256"]
    assert absent["declared_audit_policy_sha256"] != empty["declared_audit_policy_sha256"]
    assert absent["expected_inventory_supplied"] is False
    assert empty["expected_inventory_supplied"] is True


def test_freshness_budgets_and_asof_change_policy_not_receipt_fingerprint():
    rows = [row()]
    baseline = audit(rows)
    strict = audit(rows, max_age_seconds=179)
    later = audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD",
        source_id="test:feed", price_side="mid", as_of_utc=T + 241,
    )
    assert len({baseline["declared_audit_policy_sha256"],
                strict["declared_audit_policy_sha256"],
                later["declared_audit_policy_sha256"]}) == 3
    assert len({baseline["receipt_inventory_sha256"],
                strict["receipt_inventory_sha256"],
                later["receipt_inventory_sha256"]}) == 1
    assert baseline["declared_freshness_within_budget"] is True
    assert strict["declared_freshness_within_budget"] is False


@pytest.mark.parametrize("replacement,expected_text,expected_numeric", [
    ("100.50", 0, 0),
    ("100.500", 1, 0),
    ("100.51", 1, 1),
])
def test_duplicate_ohlc_revision_census(replacement, expected_text, expected_numeric):
    first = row(event="first")
    duplicate = row(event="second", received=T + 63)
    duplicate["close"] = replacement
    rows = [first, duplicate]
    original = deepcopy(rows)
    report = audit(rows)
    assert rows == original
    assert report["duplicate_minute_rows"] == 1
    assert report["changed_duplicate_ohlc_text_rows"] == expected_text
    assert report["changed_duplicate_numeric_ohlc_rows"] == expected_numeric
    assert report["structurally_clean"] is False
    assert report["source_authenticity_verified"] is False
    assert report["market_data_live"] is False
    assert report["may_execute_order"] is False


def test_duplicate_ohlc_comparisons_are_against_first_observation():
    first = row(event="first")
    revision = row(event="revision", received=T + 63)
    revision["high"] = "102.00"
    replay = row(event="replay", received=T + 64)
    report = audit([first, revision, replay])
    assert report["duplicate_minute_rows"] == 2
    assert report["changed_duplicate_ohlc_text_rows"] == 1
    assert report["changed_duplicate_numeric_ohlc_rows"] == 1
    assert report["structurally_clean"] is False


def test_duplicate_ohlc_revision_changes_receipt_digest_not_policy_digest():
    baseline = audit([row(event="first"), row(event="second", received=T + 63)])
    changed = row(event="second", received=T + 63)
    changed["low"] = "98.00"
    revised = audit([row(event="first"), changed])
    assert baseline["receipt_inventory_sha256"] != revised["receipt_inventory_sha256"]
    assert baseline["declared_audit_policy_sha256"] == revised["declared_audit_policy_sha256"]
    assert revised["changed_duplicate_numeric_ohlc_rows"] == 1


def test_unique_interior_gap_excludes_late_backfill():
    # Source-order jump observes a gap, but a later delivered candle fills it.
    rows = [row(T, event="first"),
            row(T + 120, event="jump", received=T + 182),
            row(T + 60, event="backfill", received=T + 183)]
    report = audit(rows)
    assert report["observed_gap_minutes_not_proven_missing"] == 1
    assert report["distinct_interior_unobserved_minutes_not_proven_missing"] == 0
    assert report["distinct_interior_gap_runs_not_proven_missing"] == 0
    assert report["largest_interior_gap_run_minutes_not_proven_missing"] == 0
    assert report["backward_candle_events"] == 1
    assert report["structurally_clean"] is False


def test_unique_interior_gap_ignores_replayed_minute_identity():
    rows = [row(T, event="first"),
            row(T + 120, event="jump", received=T + 182),
            row(T, event="replay", received=T + 183)]
    report = audit(rows)
    assert report["duplicate_minute_rows"] == 1
    assert report["observed_gap_minutes_not_proven_missing"] == 1
    assert report["distinct_interior_unobserved_minutes_not_proven_missing"] == 1
    assert report["distinct_interior_gap_runs_not_proven_missing"] == 1
    assert report["largest_interior_gap_run_minutes_not_proven_missing"] == 1
    assert report["may_execute_order"] is False


def test_unique_interior_gap_runs_and_longest_are_distinct():
    rows = [row(T, event="first"),
            row(T + 180, event="second", received=T + 242),
            row(T + 300, event="third", received=T + 362)]
    report = audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", as_of_utc=T + 500,
    )
    assert report["observed_gap_minutes_not_proven_missing"] == 3
    assert report["distinct_interior_unobserved_minutes_not_proven_missing"] == 3
    assert report["distinct_interior_gap_runs_not_proven_missing"] == 2
    assert report["largest_interior_gap_run_minutes_not_proven_missing"] == 2
    # A gap alone is not a verified session outage.
    assert report["session_calendar_verified"] is False


def test_unique_interior_gap_is_independent_of_declared_calendar():
    rows = [row(T, event="first"),
            row(T + 120, event="second", received=T + 182)]
    without = audit(rows)
    with_calendar = audit(rows, expected_utc_minutes=[T, T + 60, T + 120])
    for key in (
        "distinct_interior_unobserved_minutes_not_proven_missing",
        "distinct_interior_gap_runs_not_proven_missing",
        "largest_interior_gap_run_minutes_not_proven_missing",
    ):
        assert without[key] == with_calendar[key] == 1
    assert without["missing_declared_expected_minutes"] is None
    assert with_calendar["missing_declared_expected_minutes"] == 1
    assert with_calendar["structurally_clean"] is False


def test_unique_interior_gap_empty_for_single_and_contiguous_rows():
    for rows in ([row()], [row(), row(T + 60, event="next", received=T + 123)]):
        report = audit(rows)
        assert report["distinct_interior_unobserved_minutes_not_proven_missing"] == 0
        assert report["distinct_interior_gap_runs_not_proven_missing"] == 0
        assert report["largest_interior_gap_run_minutes_not_proven_missing"] == 0



def test_declared_missing_expected_runs_are_bounded_and_contiguous():
    expected = [T + i * 60 for i in range(30)]
    rows = [row(T, event="first"),
            row(T + 29 * 60, event="last", received=T + 29 * 60 + 62)]
    report = audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", as_of_utc=T + 2000, expected_utc_minutes=expected,
    )
    assert report["missing_declared_expected_minutes"] == 28
    assert report["declared_missing_expected_gap_runs"] == 1
    assert report["largest_declared_missing_expected_gap_run_minutes"] == 28
    assert report["missing_declared_expected_minute_sample_utc"] == expected[1:13]
    assert report["extra_declared_expected_minute_sample_utc"] == []
    assert report["structurally_clean"] is False
    assert report["session_calendar_verified"] is False
    assert report["may_execute_order"] is False


def test_declared_missing_runs_split_across_unsupplied_session_intervals():
    expected = [T, T + 60, T + 120, T + 600, T + 660, T + 720]
    rows = [row(T, event="first"),
            row(T + 720, event="last", received=T + 782)]
    report = audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", as_of_utc=T + 900, expected_utc_minutes=expected,
    )
    assert report["missing_declared_expected_minutes"] == 4
    assert report["declared_missing_expected_gap_runs"] == 2
    assert report["largest_declared_missing_expected_gap_run_minutes"] == 2
    assert report["missing_declared_expected_minute_sample_utc"] == [
        T + 60, T + 120, T + 600, T + 660,
    ]
    assert report["session_calendar_verified"] is False


def test_declared_extra_minute_sample_is_sorted_not_source_order():
    rows = [row(T + 120, event="later", received=T + 182),
            row(T, event="backfill", received=T + 183)]
    report = audit(rows, expected_utc_minutes=[T + 60])
    assert report["extra_minutes_outside_declared_expected"] == 2
    assert report["extra_declared_expected_minute_sample_utc"] == [T, T + 120]
    assert report["missing_declared_expected_minute_sample_utc"] == [T + 60]
    assert report["declared_missing_expected_gap_runs"] == 1
    assert report["largest_declared_missing_expected_gap_run_minutes"] == 1
    assert report["backward_candle_events"] == 1


def test_absent_and_empty_expected_run_diagnostics_are_distinct():
    absent = audit([row()])
    empty = audit([row()], expected_utc_minutes=[])
    for key in ("declared_missing_expected_gap_runs",
                "largest_declared_missing_expected_gap_run_minutes",
                "missing_declared_expected_minute_sample_utc",
                "extra_declared_expected_minute_sample_utc"):
        assert absent[key] is None
    assert empty["declared_missing_expected_gap_runs"] == 0
    assert empty["largest_declared_missing_expected_gap_run_minutes"] == 0
    assert empty["missing_declared_expected_minute_sample_utc"] == []
    assert empty["extra_declared_expected_minute_sample_utc"] == [T]
    assert absent["receipt_inventory_sha256"] == empty["receipt_inventory_sha256"]
    assert absent["declared_audit_policy_sha256"] != empty["declared_audit_policy_sha256"]


def test_declared_overdue_missing_expected_minutes_exclude_not_yet_due():
    # Default declared budgets: 60s to finalize and 30s to transport.
    # At T+240, T+60 is overdue; T+120 and T+180 are still pending.
    report = audit([row()], expected_utc_minutes=[T, T + 60, T + 120, T + 180])
    assert report["missing_declared_expected_minutes"] == 3
    assert report["declared_overdue_missing_expected_minutes"] == 1
    assert report["declared_pending_missing_expected_minutes"] == 2
    assert report["overdue_declared_expected_minute_sample_utc"] == [T + 60]
    assert report["structurally_clean"] is False
    assert report["session_calendar_verified"] is False
    assert report["may_execute_order"] is False


def test_declared_overdue_boundary_requires_clock_strictly_after_deadline():
    kwargs = dict(provider="synthetic", instrument="XAU/USD",
                  source_id="test:feed", price_side="mid",
                  expected_utc_minutes=[T, T + 60])
    at_deadline = audit_declared_completed_m1_receipts(
        [row()], as_of_utc=T + 210, **kwargs)
    after_deadline = audit_declared_completed_m1_receipts(
        [row()], as_of_utc=T + 211, **kwargs)
    assert at_deadline["declared_overdue_missing_expected_minutes"] == 0
    assert at_deadline["declared_pending_missing_expected_minutes"] == 1
    assert after_deadline["declared_overdue_missing_expected_minutes"] == 1
    assert after_deadline["declared_pending_missing_expected_minutes"] == 0


def test_declared_overdue_census_uses_configured_budgets_without_changing_receipt_hash():
    expected = [T, T + 60]
    normal = audit([row()], expected_utc_minutes=expected)
    relaxed = audit([row()], expected_utc_minutes=expected,
                    max_finalization_lag_seconds=120)
    assert normal["declared_overdue_missing_expected_minutes"] == 1
    assert relaxed["declared_overdue_missing_expected_minutes"] == 0
    assert relaxed["declared_pending_missing_expected_minutes"] == 1
    assert normal["receipt_inventory_sha256"] == relaxed["receipt_inventory_sha256"]
    assert normal["declared_audit_policy_sha256"] != relaxed["declared_audit_policy_sha256"]
    assert normal["structurally_clean"] == relaxed["structurally_clean"] is False


def test_absent_and_empty_expected_overdue_diagnostics_are_distinct():
    absent = audit([row()])
    empty = audit([row()], expected_utc_minutes=[])
    for key in ("declared_overdue_missing_expected_minutes",
                "declared_pending_missing_expected_minutes",
                "overdue_declared_expected_minute_sample_utc"):
        assert absent[key] is None
    assert empty["declared_overdue_missing_expected_minutes"] == 0
    assert empty["declared_pending_missing_expected_minutes"] == 0
    assert empty["overdue_declared_expected_minute_sample_utc"] == []


def test_overdue_gap_runs_split_at_declared_session_breaks():
    expected = [T, T + 60, T + 120, T + 600, T + 660, T + 720]
    report = audit_declared_completed_m1_receipts(
        [row(T, event="first"), row(T + 720, event="last", received=T + 782)],
        provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", as_of_utc=T + 800, expected_utc_minutes=expected,
    )
    assert report["missing_declared_expected_minutes"] == 4
    assert report["declared_overdue_missing_expected_minutes"] == 3
    assert report["declared_pending_missing_expected_minutes"] == 1
    assert report["declared_overdue_missing_expected_gap_runs"] == 2
    assert report["largest_declared_overdue_missing_expected_gap_run_minutes"] == 2
    assert report["overdue_declared_expected_minute_sample_utc"] == [
        T + 60, T + 120, T + 600,
    ]
    assert report["pending_declared_expected_minute_sample_utc"] == [T + 660]
    assert report["structurally_clean"] is False
    assert report["session_calendar_verified"] is False
    assert report["may_execute_order"] is False


def test_overdue_run_strict_deadline_and_empty_overdue_population():
    kwargs = dict(
        provider="synthetic", instrument="XAU/USD", source_id="test:feed",
        price_side="mid", expected_utc_minutes=[T, T + 60],
    )
    at_deadline = audit_declared_completed_m1_receipts(
        [row()], as_of_utc=T + 210, **kwargs,
    )
    after_deadline = audit_declared_completed_m1_receipts(
        [row()], as_of_utc=T + 211, **kwargs,
    )
    assert at_deadline["declared_overdue_missing_expected_gap_runs"] == 0
    assert at_deadline["largest_declared_overdue_missing_expected_gap_run_minutes"] == 0
    assert at_deadline["pending_declared_expected_minute_sample_utc"] == [T + 60]
    assert after_deadline["declared_overdue_missing_expected_gap_runs"] == 1
    assert after_deadline["largest_declared_overdue_missing_expected_gap_run_minutes"] == 1
    assert after_deadline["pending_declared_expected_minute_sample_utc"] == []


def test_overdue_run_absent_vs_empty_and_pending_sample_bounded():
    absent = audit([row()])
    empty = audit([row()], expected_utc_minutes=[])
    keys = (
        "pending_declared_expected_minute_sample_utc",
        "declared_overdue_missing_expected_gap_runs",
        "largest_declared_overdue_missing_expected_gap_run_minutes",
    )
    for key in keys:
        assert absent[key] is None
    assert empty["pending_declared_expected_minute_sample_utc"] == []
    assert empty["declared_overdue_missing_expected_gap_runs"] == 0
    assert empty["largest_declared_overdue_missing_expected_gap_run_minutes"] == 0
    expected = [T + 60 * i for i in range(30)]
    report = audit([row()], expected_utc_minutes=expected)
    assert report["declared_overdue_missing_expected_minutes"] == 1
    assert report["declared_pending_missing_expected_minutes"] == 28
    assert report["pending_declared_expected_minute_sample_utc"] == expected[2:14]
    assert len(report["pending_declared_expected_minute_sample_utc"]) == 12
    assert report["declared_overdue_missing_expected_gap_runs"] == 1
    assert report["largest_declared_overdue_missing_expected_gap_run_minutes"] == 1
