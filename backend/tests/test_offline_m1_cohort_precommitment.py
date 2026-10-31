"""Synthetic tests for an externally anchored M1 source-cohort identity census."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.offline_m1_cohort_precommitment import (
    prepare_m1_cohort_precommitment, require_m1_precommitted_cohort,
)
from app.offline_m1_multi_archive_census import BODY_KEYS, POLICY


def _rehash(report):
    body = {key: report[key] for key in BODY_KEYS}
    report["research_sha256"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()).hexdigest()
    return report


def _receipt(archive, manifest, count=3, instrument="NSXUSD", provider="HistData"):
    dev = count * 7 // 10
    later = count - dev
    dw, lw = dev // 2, later // 2

    def part(n, wins):
        return {
            "count": n, "mean_gross_bps": 1.0 if n else None,
            "mean_net_bps_by_roundtrip_cost": {
                str(c): 1.0 - c if n else None for c in (0, 5, 10, 20)
            },
            "gross_win_fraction": round(wins / n, 6) if n else None,
        }

    return _rehash({
        "research_schema_version": 1, "policy": POLICY,
        "source": {
            "instrument": instrument, "provider": provider,
            "archive_sha256": archive * 64,
            "price_side": "UNVERIFIED_SINGLE_SIDE",
            "time_convention": "SOURCE_WALL_UNVERIFIED",
        },
        "bar_count": 100, "bar_manifest_sha256": manifest * 64,
        "timestamp_discontinuities": 0, "backward_jumps": 0,
        "adjacent_duplicates": 0, "sweep_count": count,
        "ambiguous_count": 0, "confirmed_count": count,
        "censored_gap_or_end": 0, "excluded_overlap": 0,
        "horizon_minutes": 15, "roundtrip_cost_bps": [0, 5, 10, 20],
        "development_exploratory": part(dev, dw),
        "later_exploratory_not_holdout": part(later, lw),
        "all_exploratory": part(count, dw + lw),
        "research_only": True, "trade_authorized": False,
        "verified_profitability": False, "protected_holdout": False,
        "source_authenticity_verified": False,
        "executable_quotes_verified": False, "financing_modeled": False,
        "market_calendar_verified": False,
    })


def _identities(reports):
    return [{
        "instrument": r["source"]["instrument"],
        "provider": r["source"]["provider"],
        "archive_sha256": r["source"]["archive_sha256"],
        "bar_manifest_sha256": r["bar_manifest_sha256"],
    } for r in reports]


def _three():
    return [_receipt("a", "b", 2), _receipt("c", "d", 3), _receipt("e", "f", 4)]


def test_precommitment_is_order_independent_and_outcome_free():
    entries = _identities(_three())
    first = prepare_m1_cohort_precommitment(entries)
    assert first == prepare_m1_cohort_precommitment(entries[::-1])
    assert first["archive_count"] == 3
    assert not any(k in first for k in ("mean_gross_bps", "win_fraction", "outcomes"))
    assert not first["trade_authorized"] and not first["protected_holdout"]


def test_matching_cohort_reports_are_accepted_only_as_exploratory():
    reports = _three()
    expected = prepare_m1_cohort_precommitment(_identities(reports))["source_cohort_sha256"]
    result = require_m1_precommitted_cohort(reports[::-1], expected)
    assert result["archive_count"] == 3
    assert result["source_cohort_sha256"] == expected
    assert result["groups"][0]["evaluated_count"] == 9
    assert result["research_only"] and not result["trade_authorized"]
    assert not result["protected_holdout"] and not result["verified_profitability"]
    assert not result["executable_quotes_verified"]


def test_missing_archive_rejected_even_when_remaining_census_valid():
    reports = _three()
    expected = prepare_m1_cohort_precommitment(_identities(reports))["source_cohort_sha256"]
    with pytest.raises(ValueError, match="differs"):
        require_m1_precommitted_cohort(reports[:2], expected)


@pytest.mark.parametrize("mutation", ["archive", "manifest", "instrument", "provider"])
def test_substitution_cannot_rewrite_registered_cohort(mutation):
    reports = _three()
    expected = prepare_m1_cohort_precommitment(_identities(reports))["source_cohort_sha256"]
    changed = deepcopy(reports)
    if mutation == "archive":
        changed[1]["source"]["archive_sha256"] = "1" * 64
    elif mutation == "manifest":
        changed[1]["bar_manifest_sha256"] = "2" * 64
    elif mutation == "instrument":
        changed[1]["source"]["instrument"] = "XAUUSD"
    else:
        changed[1]["source"]["provider"] = "OtherFeed"
    _rehash(changed[1])
    with pytest.raises(ValueError, match="differs"):
        require_m1_precommitted_cohort(changed, expected)


@pytest.mark.parametrize("expected", ["", "z" * 64, "a" * 63, None, 1, "A" * 64])
def test_external_digest_must_be_exact_sha256(expected):
    with pytest.raises(ValueError, match="Independently retained"):
        require_m1_precommitted_cohort(_three(), expected)


def test_valid_but_different_expected_digest_rejected():
    with pytest.raises(ValueError, match="differs"):
        require_m1_precommitted_cohort(_three(), "0" * 64)


def test_duplicate_manifest_rejected_before_digest():
    entries = _identities(_three())
    entries[1]["bar_manifest_sha256"] = entries[0]["bar_manifest_sha256"]
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_m1_cohort_precommitment(entries)


def test_duplicate_archive_rejected_before_digest():
    entries = _identities(_three())
    entries[1]["archive_sha256"] = entries[0]["archive_sha256"]
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_m1_cohort_precommitment(entries)


@pytest.mark.parametrize("field,value", [
    ("instrument", "bad name"), ("provider", ""),
    ("archive_sha256", "g" * 64), ("bar_manifest_sha256", "a" * 63),
])
def test_malformed_source_identity_rejected(field, value):
    entries = _identities(_three())
    entries[0][field] = value
    with pytest.raises(ValueError, match="Invalid"):
        prepare_m1_cohort_precommitment(entries)


def test_uncommitted_extra_field_rejected():
    entries = _identities(_three())
    entries[0]["performance_hint"] = 100
    with pytest.raises(ValueError, match="Exact"):
        prepare_m1_cohort_precommitment(entries)


def test_receipt_self_hash_still_validated_before_cohort_check():
    reports = _three()
    expected = prepare_m1_cohort_precommitment(_identities(reports))["source_cohort_sha256"]
    reports[0]["all_exploratory"]["mean_gross_bps"] = 9000
    with pytest.raises(ValueError, match="fingerprint"):
        require_m1_precommitted_cohort(reports, expected)


def test_empty_archive_not_silently_dropped_from_complete_identity_set():
    reports = [_receipt("a", "b", 0), _receipt("c", "d", 3)]
    expected = prepare_m1_cohort_precommitment(_identities(reports))["source_cohort_sha256"]
    result = require_m1_precommitted_cohort(reports, expected)
    assert result["groups"][0]["status"] == "INCOMPLETE_ARCHIVE_COVERAGE"
    assert result["groups"][0]["weighted_mean_gross_bps_rounded_receipts"] is None


@pytest.mark.parametrize("entries", [[], [{}], "not-a-list", [None, None]])
def test_invalid_precommitment_population_rejected(entries):
    with pytest.raises(ValueError):
        prepare_m1_cohort_precommitment(entries)


def test_more_than_64_archives_rejected():
    entries = [{
        "instrument": "NSXUSD", "provider": "HistData",
        "archive_sha256": f"{i:064x}",
        "bar_manifest_sha256": f"{i+1000:064x}",
    } for i in range(65)]
    with pytest.raises(ValueError, match="2..64"):
        prepare_m1_cohort_precommitment(entries)
