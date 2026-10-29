"""Synthetic declared-session gap run tests; no network or market prices."""
from dataclasses import replace
import pytest

from app.declared_m1_gap_runs import audit_declared_m1_gap_runs
from app.expected_bar_manifest import compile_expected_m1_manifest

T = 1790000040


def manifest(**kwargs):
    data = dict(provider="fixture", symbol="XAU/USD", venue="UNVERIFIED",
                price_side="UNSPECIFIED", calendar_id="synthetic",
                calendar_revision="r1", calendar_source="operator fixture",
                observed_at_utc=T + 600,
                sessions_utc=[(T, T+180), (T+300, T+480)],
                exclusions_utc=[(T+60, T+120)])
    return compile_expected_m1_manifest(**(data | kwargs))


def audit(rows, **kwargs):
    return audit_declared_m1_gap_runs(manifest(), rows, **kwargs)


def test_full_coverage_is_not_live_or_authenticated():
    report = audit([T, T+120, T+300, T+360, T+420])
    assert report["status"] == "DECLARED_COVERAGE_COMPLETE_UNVERIFIED"
    assert report["missing_expected_minutes"] == 0
    assert report["missing_gap_runs"] == 0
    assert report["gap_run_length_histogram"] == {}
    assert report["expected_calendar_verified"] is False
    assert report["source_authenticated"] is False
    assert report["live"] is False and report["may_execute_order"] is False


def test_missing_runs_do_not_cross_closure_or_session_break():
    report = audit([])
    assert report["missing_expected_minutes"] == 5
    assert report["missing_gap_runs"] == 3
    assert report["longest_missing_gap_minutes"] == 3
    assert report["gap_run_length_histogram"] == {"1": 2, "3": 1}
    assert report["missing_gap_samples"] == [
        {"start_utc": T, "end_exclusive_utc": T+60, "minutes": 1},
        {"start_utc": T+120, "end_exclusive_utc": T+180, "minutes": 1},
        {"start_utc": T+300, "end_exclusive_utc": T+480, "minutes": 3},
    ]


def test_duplicate_and_closed_minutes_are_review_only():
    report = audit([T, T, T+60, T+120, T+300, T+360, T+420])
    assert report["missing_expected_minutes"] == 0
    assert report["duplicate_observation_rows"] == 1
    assert report["unexpected_unique_minutes"] == 1
    assert report["unexpected_minute_samples"] == [T+60]
    assert report["status"] == "REVIEW_REQUIRED"


def test_unexpected_minutes_attributed_to_exclusion_or_outside_session():
    rows = [T, T+60, T+60, T+120, T+180, T+240, T+480, T+540]
    report = audit(rows, sample_limit=2)
    assert report["unexpected_unique_minutes"] == 5
    assert report["observed_in_declared_exclusions_unique_minutes"] == 1
    assert report["observed_outside_declared_sessions_unique_minutes"] == 4
    assert report["observed_in_declared_exclusions_samples"] == [T+60]
    assert report["observed_outside_declared_sessions_samples"] == [T+180, T+240]
    assert report["duplicate_observation_rows"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_unexpected_attribution_zero_samples_preserves_exact_counts():
    report = audit([T+60, T+180, T+480], sample_limit=0)
    assert report["unexpected_unique_minutes"] == 3
    assert report["observed_in_declared_exclusions_unique_minutes"] == 1
    assert report["observed_outside_declared_sessions_unique_minutes"] == 2
    assert report["observed_in_declared_exclusions_samples"] == []
    assert report["observed_outside_declared_sessions_samples"] == []


def test_gap_run_is_split_by_present_minute():
    report = audit([T, T+300, T+420])
    assert report["missing_expected_minutes"] == 2
    assert report["missing_gap_runs"] == 2
    assert report["gap_run_length_histogram"] == {"1": 2}


def test_adjacent_sessions_never_merge_gaps():
    m = manifest(sessions_utc=[(T, T+120), (T+120, T+240)], exclusions_utc=[])
    r = audit_declared_m1_gap_runs(m, [])
    assert r["missing_gap_runs"] == 2
    assert r["gap_run_length_histogram"] == {"2": 2}


def test_bounded_sample_zero_still_counts_all():
    report = audit([], sample_limit=0)
    assert report["missing_gap_samples"] == []
    assert report["missing_expected_minutes"] == 5


@pytest.mark.parametrize("bad", [True, 0.0, T+1, T+600, -60, "1790000040"])
def test_invalid_observation_rejected(bad):
    with pytest.raises(ValueError, match="Invalid or unfinished"):
        audit([bad])


@pytest.mark.parametrize("bad", [None, (), "", [T]*20001])
def test_invalid_observation_container_rejected(bad):
    with pytest.raises(ValueError, match="Bounded observation"):
        audit_declared_m1_gap_runs(manifest(), bad)


@pytest.mark.parametrize("bad", [True, -1, 51, "10"])
def test_invalid_sample_limit_rejected(bad):
    with pytest.raises(ValueError, match="Bounded observation"):
        audit([], sample_limit=bad)


def test_manifest_tamper_rejected():
    m = manifest()
    with pytest.raises(ValueError, match="mutated"):
        audit_declared_m1_gap_runs(replace(m, expected_minutes=(T,)), [T])


def test_sample_limit_applies_to_unexpected_and_missing():
    r = audit([T+240, T+480, T+540], sample_limit=1)
    assert len(r["unexpected_minute_samples"]) == 1
    assert len(r["missing_gap_samples"]) == 1
    assert r["unexpected_unique_minutes"] == 3


def test_no_observation_bytes_or_prices_in_report():
    r = audit([T])
    assert "open" not in r and "close" not in r
    assert r["unique_observed_expected_minutes"] == 1
