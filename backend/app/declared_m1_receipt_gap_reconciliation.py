"""Offline cross-check of declared completed-M1 receipts and session gap runs.

This is a consistency audit, not provider authentication, a venue calendar,
licensed data access, a live-feed assertion or a forecasting/trading gate.
"""
from __future__ import annotations

from .declared_m1_gap_runs import audit_declared_m1_gap_runs
from .expected_bar_manifest import (
    ExpectedM1Manifest,
    audit_m1_receipts_against_manifest,
)


def audit_declared_m1_receipt_gap_reconciliation(
    receipts: list[dict],
    manifest: ExpectedM1Manifest,
    *,
    max_receipt_lag_seconds: int = 120,
    max_observation_age_seconds: int = 180,
    max_expected_close_age_seconds: int = 180,
    sample_limit: int = 20,
) -> dict:
    """Reconcile two independent *algorithms* over the same declared inputs.

    The receipt census validates schema, OHLC, source identity and declared
    freshness first. The gap audit separately checks input order, closures,
    per-session missing runs and trailing expected-minute coverage. Their
    populations must agree exactly; neither input is independently trusted.
    """
    limits = dict(
        max_receipt_lag_seconds=max_receipt_lag_seconds,
        max_observation_age_seconds=max_observation_age_seconds,
        max_expected_close_age_seconds=max_expected_close_age_seconds,
        sample_limit=sample_limit,
    )
    # This call validates the entire receipt schema and frozen manifest before
    # any fields are read. Do not skip it even when the receipt list is empty.
    census = audit_m1_receipts_against_manifest(receipts, manifest, **limits)
    gaps = audit_declared_m1_gap_runs(
        manifest, [row["bar_start_utc"] for row in receipts],
        sample_limit=sample_limit,
    )
    # Preserve the caller's declared receipt arrival order. A bar-start-sorted
    # list can hide a receipt-clock reversal even when all bars are present.
    # These are untrusted timestamps: a reversal is a review signal, not proof
    # of clock tampering or an authenticated append-only feed.
    backward_receipt_times = 0
    backward_receipt_time_samples: list[dict[str, int]] = []
    previous_receipt_utc: int | None = None
    for row in receipts:
        received_utc = row["received_at_utc"]
        if previous_receipt_utc is not None and received_utc < previous_receipt_utc:
            backward_receipt_times += 1
            if len(backward_receipt_time_samples) < sample_limit:
                backward_receipt_time_samples.append({
                    "previous_received_at_utc": previous_receipt_utc,
                    "received_at_utc": received_utc,
                })
        previous_receipt_utc = received_utc
    # Attribute declared receipt lag to the expected session containing each
    # bar start. Keep unexpected/closure receipts separate: a late closure bar
    # must not be mistaken for evidence of a delayed open-session candle.
    # These are caller-declared times, not authenticated network latency.
    expected_set = set(manifest.expected_minutes)
    session_by_expected_minute = {
        minute: index
        for index, (start, end) in enumerate(manifest.sessions_utc)
        for minute in range(start, end, 60)
        if minute in expected_set
    }
    session_receipt_lag = [
        {
            "start_utc": start,
            "end_exclusive_utc": end,
            "expected_receipt_rows": 0,
            "late_expected_receipt_rows": 0,
            "max_declared_receipt_lag_seconds": None,
        }
        for start, end in manifest.sessions_utc
    ]
    unexpected_receipt_rows = 0
    late_unexpected_receipt_rows = 0
    for row in receipts:
        lag = row["received_at_utc"] - row["bar_start_utc"] - 60
        session_index = session_by_expected_minute.get(row["bar_start_utc"])
        if session_index is None:
            unexpected_receipt_rows += 1
            late_unexpected_receipt_rows += lag > max_receipt_lag_seconds
            continue
        bucket = session_receipt_lag[session_index]
        bucket["expected_receipt_rows"] += 1
        bucket["late_expected_receipt_rows"] += lag > max_receipt_lag_seconds
        previous_max = bucket["max_declared_receipt_lag_seconds"]
        bucket["max_declared_receipt_lag_seconds"] = (
            lag if previous_max is None else max(previous_max, lag)
        )
    if (sum(row["expected_receipt_rows"] for row in session_receipt_lag)
            + unexpected_receipt_rows != census["receipt_rows"]
            or sum(row["late_expected_receipt_rows"] for row in session_receipt_lag)
            + late_unexpected_receipt_rows != census["late_receipt_rows"]):
        raise ValueError("Declared receipt/session lag attribution failed")
    equalities = (
        (census["calendar_manifest_sha256"], gaps["calendar_manifest_sha256"]),
        (census["expected_minutes"], gaps["expected_minutes"]),
        (census["missing_expected_minutes"], gaps["missing_expected_minutes"]),
        (census["unexpected_observed_minutes"], gaps["unexpected_unique_minutes"]),
        (census["duplicate_receipt_rows"], gaps["duplicate_observation_rows"]),
        (census["unique_observed_minutes"],
         gaps["unique_observed_expected_minutes"] + gaps["unexpected_unique_minutes"]),
    )
    if any(left != right for left, right in equalities):
        raise ValueError("Declared receipt/gap population reconciliation failed")
    clean = (
        census["status"] == "INTERNAL_CENSUS_ONLY_NOT_LIVE"
        and gaps["status"] == "DECLARED_COVERAGE_COMPLETE_UNVERIFIED"
        and backward_receipt_times == 0
    )
    return {
        "protocol": "declared-m1-receipt-gap-reconciliation-v1",
        "status": ("DECLARED_RECONCILED_UNVERIFIED" if clean else "REVIEW_REQUIRED"),
        "calendar_manifest_sha256": manifest.manifest_sha256,
        "receipt_input_sha256": census["input_sha256"],
        "expected_minutes": gaps["expected_minutes"],
        "missing_expected_minutes": gaps["missing_expected_minutes"],
        "missing_gap_runs": gaps["missing_gap_runs"],
        "trailing_missing_expected_minutes": gaps["trailing_missing_expected_minutes"],
        "unexpected_unique_minutes": gaps["unexpected_unique_minutes"],
        "duplicate_receipt_rows": gaps["duplicate_observation_rows"],
        "backward_timestamp_transitions": gaps["backward_timestamp_transitions"],
        "backward_receipt_time_transitions": backward_receipt_times,
        "backward_receipt_time_samples": backward_receipt_time_samples,
        "declared_session_coverage": gaps["declared_session_coverage"],
        "declared_session_receipt_lag": session_receipt_lag,
        "unexpected_receipt_rows": unexpected_receipt_rows,
        "late_unexpected_receipt_rows": late_unexpected_receipt_rows,
        "receipt_census": census,
        "session_gap_audit": gaps,
        "independent_calendar_verified": False,
        "source_authenticated": False,
        "provider_entitlement_verified": False,
        "server_receipt_clock_attested": False,
        "executable_bid_ask_verified": False,
        "live": False,
        "forecast_ready": False,
        "may_execute_order": False,
    }
