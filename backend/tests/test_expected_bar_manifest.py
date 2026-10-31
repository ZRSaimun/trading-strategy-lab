"""Synthetic UTC session/closure manifest regressions; no vendor or live feed."""
from dataclasses import replace

import pytest

from app.expected_bar_manifest import (
    audit_m1_receipts_against_manifest, compile_expected_m1_manifest,
)

T = 1790000040
NOW = T + 320
BASE = dict(
    provider="fixture", symbol="XAU/USD", venue="synthetic", price_side="BID",
    calendar_id="fixture sessions", calendar_revision="r1",
    calendar_source="operator declared bulletin",
    observed_at_utc=NOW,
    sessions_utc=[(T, T + 120), (T + 180, T + 300)],
    exclusions_utc=[(T + 60, T + 120)],
)


def manifest(**changes):
    return compile_expected_m1_manifest(**(BASE | changes))


def bar(t, **changes):
    return dict(
        provider="fixture", symbol="XAU/USD", venue="synthetic", price_side="BID",
        bar_start_utc=t, received_at_utc=t + 65,
        open=100., high=102., low=99., close=101.,
        **changes,
    )


def test_declared_breaks_and_closures_exclude_exact_minutes():
    m = manifest()
    assert m.expected_minutes == (T, T + 180, T + 240)
    assert len(m.manifest_sha256) == 64
    r = audit_m1_receipts_against_manifest([bar(t) for t in m.expected_minutes], m)
    assert r["expected_minutes"] == 3
    assert r["missing_expected_minutes"] == 0
    assert r["declared_session_intervals"] == 2
    assert r["declared_excluded_minutes"] == 1
    assert r["status"] == "INTERNAL_CENSUS_ONLY_NOT_LIVE"
    assert r["expected_calendar_verified"] is False
    assert r["source_authenticated"] is False
    assert r["live"] is False and r["may_execute_order"] is False


def test_gap_and_unexpected_closed_minute_fail_closed():
    m = manifest()
    r = audit_m1_receipts_against_manifest([bar(T), bar(T + 60), bar(T + 240)], m)
    assert r["missing_expected_minutes"] == 1
    assert r["unexpected_observed_minutes"] == 1
    assert r["status"] == "REVIEW_REQUIRED"


def test_replay_of_old_expected_bar_does_not_pass_freshness():
    m = manifest()
    r = audit_m1_receipts_against_manifest(
        [bar(T)], m, max_expected_close_age_seconds=60)
    assert r["missing_expected_minutes"] == 2
    assert r["stale_expected_receipts"] is True
    assert r["status"] == "REVIEW_REQUIRED"


def test_provenance_revision_and_exclusions_bound_fingerprint():
    a = manifest()
    assert a == manifest()
    assert a.manifest_sha256 != manifest(calendar_revision="r2").manifest_sha256
    assert a.manifest_sha256 != manifest(exclusions_utc=[]).manifest_sha256
    assert a.manifest_sha256 != manifest(calendar_source="different source").manifest_sha256


def test_manifest_cannot_be_tampered_after_compilation():
    m = manifest()
    for changed in (
        replace(m, expected_minutes=(T,)),
        replace(m, calendar_revision="r2"),
        replace(m, manifest_sha256="0" * 64),
        replace(m, observed_at_utc=NOW + 100),
    ):
        with pytest.raises(ValueError):
            audit_m1_receipts_against_manifest([bar(T)], changed)


@pytest.mark.parametrize("changes", [
    {"sessions_utc": []},
    {"sessions_utc": [(T, T + 120), (T + 60, T + 180)]},
    {"sessions_utc": [(T + 180, T + 300), (T, T + 120)]},
    {"sessions_utc": [(T + 1, T + 120)]},
    {"sessions_utc": [(True, T + 120)]},
    {"sessions_utc": [(T, T + 360)]},
    {"sessions_utc": [(T, T)]},
    {"sessions_utc": [(T, T + 600_060)]},
    {"sessions_utc": [(T, T + 120)] * 101},
    {"exclusions_utc": [(T + 120, T + 180)]},
    {"exclusions_utc": [(T + 60, T + 240)]},
    {"exclusions_utc": [(T + 180, T + 240), (T + 180, T + 240)]},
    {"exclusions_utc": [(T, T + 300)]},
    {"exclusions_utc": [(T, T + 120), (T + 180, T + 300)]},
    {"observed_at_utc": True},
    {"observed_at_utc": NOW - 100},
    {"calendar_revision": ""},
    {"calendar_source": "invalid\\nsource"},
    {"price_side": "CFD"},
])
def test_invalid_or_unjustified_schedule_rejected(changes):
    with pytest.raises(ValueError):
        manifest(**changes)


def test_no_identity_substitution_and_no_live_flag():
    m = manifest()
    row = bar(T)
    row["symbol"] = "NQ"
    with pytest.raises(ValueError):
        audit_m1_receipts_against_manifest([row], m)
    with pytest.raises(ValueError):
        audit_m1_receipts_against_manifest([], m, live=True)


def test_expected_population_boundary():
    big = manifest(
        observed_at_utc=T + 600_000,
        sessions_utc=[(T, T + 600_000)],
        exclusions_utc=[],
    )
    assert len(big.expected_minutes) == 10_000
    with pytest.raises(ValueError):
        manifest(
            observed_at_utc=T + 600_060,
            sessions_utc=[(T, T + 600_060)],
            exclusions_utc=[],
        )
