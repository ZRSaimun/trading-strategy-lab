"""Synthetic-only first-seen M1 delivery triage; no network or market data."""
from copy import deepcopy

from app.declared_completed_m1_receipts import audit_declared_completed_m1_receipts

T = 1_790_000_100
assert T % 60 == 0


def row(start, event, received):
    return {
        "event_id": event, "provider": "synthetic",
        "instrument": "XAU/USD", "source_id": "synthetic:test",
        "price_side": "mid", "minute_start_utc": start,
        "finalized_at_utc": start + 61, "received_at_utc": received,
        "is_final": True, "open": "100.00", "high": "101.00",
        "low": "99.00", "close": "100.50",
    }


def audit(rows, as_of=T + 1600):
    return audit_declared_completed_m1_receipts(
        rows, provider="synthetic", instrument="XAU/USD",
        source_id="synthetic:test", price_side="mid", as_of_utc=as_of,
    )


def test_late_first_seen_backfills_count_once_even_with_late_replay():
    rows = [
        row(T + 180, "high", T + 242),
        row(T, "old", T + 243),
        row(T + 60, "middle", T + 244),
        row(T + 60, "replay", T + 245),
    ]
    original = deepcopy(rows)
    report = audit(rows)
    assert rows == original
    assert report["declared_arrived_after_budget_rows"] == 3
    assert report["declared_arrived_after_budget_distinct_minutes"] == 2
    assert report["declared_first_seen_after_budget_minutes"] == 2
    assert report["declared_first_seen_after_budget_minute_sample_utc"] == [
        T, T + 60,
    ]
    assert report["out_of_order_first_seen_minutes"] == 2
    assert report["declared_late_first_seen_backfill_minutes"] == 2
    assert report["declared_late_first_seen_backfill_minute_sample_utc"] == [
        T, T + 60,
    ]
    assert report["may_execute_order"] is False


def test_late_duplicate_does_not_retroactively_make_first_receipt_late():
    # T+60 arrived first, but T was still within its own declared 150s deadline.
    rows = [
        row(T + 60, "high", T + 122),
        row(T, "backfill", T + 123),
        row(T, "late-replay", T + 200),
    ]
    report = audit(rows)
    assert report["out_of_order_first_seen_minutes"] == 1
    assert report["declared_arrived_after_budget_rows"] == 1
    assert report["declared_arrived_after_budget_distinct_minutes"] == 1
    assert report["declared_first_seen_after_budget_minutes"] == 0
    assert report["declared_late_first_seen_backfill_minutes"] == 0
    assert report["declared_first_seen_after_budget_minute_sample_utc"] == []
    assert report["declared_late_first_seen_backfill_minute_sample_utc"] == []
    assert report["structurally_clean"] is False
    assert report["source_authenticity_verified"] is False


def test_exact_composite_deadline_is_not_first_seen_late():
    report = audit([
        row(T, "first", T + 150),
        row(T, "late-replay", T + 151),
    ])
    assert report["declared_arrived_after_budget_rows"] == 1
    assert report["declared_first_seen_after_budget_minutes"] == 0
    assert report["declared_late_first_seen_backfill_minutes"] == 0
    # Stage-specific lag breach remains quarantined at the composite boundary.
    assert report["transport_lag_exceeded_rows"] == 2
    assert report["structurally_clean"] is False


def test_first_seen_samples_are_sorted_bounded_and_digest_is_unchanged():
    rows = [row(T + 1200, "high", T + 1262)]
    rows += [
        row(T + i * 60, f"backfill-{i}", T + 1300 + i)
        for i in range(16)
    ]
    report = audit(rows)
    assert report["declared_first_seen_after_budget_minutes"] == 16
    assert report["declared_late_first_seen_backfill_minutes"] == 16
    assert report["declared_first_seen_after_budget_minute_sample_utc"] == [
        T + i * 60 for i in range(12)
    ]
    assert report["declared_late_first_seen_backfill_minute_sample_utc"] == [
        T + i * 60 for i in range(12)
    ]
    assert len(report["receipt_inventory_sha256"]) == 64
    assert len(report["declared_audit_policy_sha256"]) == 64
    assert report["market_data_live"] is False
    assert report["research_ready"] is False
    assert report["may_execute_order"] is False
