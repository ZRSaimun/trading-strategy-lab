"""Synthetic-only tests for precommitted cross-auditor M1 reconciliation."""
from copy import deepcopy
import hashlib
import json

import pytest

from app import offline_m1_precommitted_research_bundle as bundle
from app.offline_m1_cohort_precommitment import prepare_m1_cohort_precommitment
from app.offline_m1_multi_archive_census import BODY_KEYS, POLICY


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

    report = {
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
    }
    return _rehash(report)


def _rehash(report):
    report["research_sha256"] = hashlib.sha256(json.dumps(
        {key: report[key] for key in BODY_KEYS},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()
    return report


def _three():
    return [_receipt("a", "b", 2), _receipt("c", "d", 3),
            _receipt("e", "f", 4)]


def _digest(reports):
    return prepare_m1_cohort_precommitment([{
        "instrument": r["source"]["instrument"],
        "provider": r["source"]["provider"],
        "archive_sha256": r["source"]["archive_sha256"],
        "bar_manifest_sha256": r["bar_manifest_sha256"],
    } for r in reports])["source_cohort_sha256"]


def test_complete_source_bundle_reconciles_all_five_auditors():
    reports = _three()
    output = bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))
    assert output["groups"][0]["archive_count"] == 3
    assert output["groups"][0]["evaluated_outcome_count"] == 9
    assert output["groups"][0]["fixed_direction_net_bps_at_5_illustrative"] == -4.0
    assert output["groups"][0]["fixed_direction_mean_nonpositive_at_5_illustrative"] is True
    assert output["groups"][0]["status"] == "DESCRIPTIVE_RECONCILED_ONLY"
    assert not output["trade_authorized"] and not output["verified_profitability"]
    assert not output["independent_precommitment_verified"]
    assert not output["protected_holdout"] and not output["executable_quotes_verified"]


def test_order_independent_bundle_digest():
    reports = _three()
    expected = _digest(reports)
    assert bundle.audit_m1_precommitted_research_bundle(
        reports, expected)["research_sha256"] == bundle.audit_m1_precommitted_research_bundle(
            reports[::-1], expected)["research_sha256"]


def test_incomplete_archive_quarantines_all_source_performance():
    reports = [_receipt("a", "b", 0), _receipt("c", "d", 3)]
    output = bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))
    group = output["groups"][0]
    assert group["status"] == "INCOMPLETE_ARCHIVE_COVERAGE"
    assert group["fixed_direction_net_bps_at_5_illustrative"] is None
    assert group["fixed_direction_mean_nonpositive_at_5_illustrative"] is None


def test_incomplete_source_does_not_hide_complete_other_source():
    reports = [_receipt("a", "b", 0), _receipt("c", "d", 3),
               _receipt("e", "f", 4, instrument="XAUUSD"),
               _receipt("1", "2", 5, instrument="XAUUSD")]
    output = bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))
    by_source = {g["instrument"]: g for g in output["groups"]}
    assert by_source["NSXUSD"]["fixed_direction_net_bps_at_5_illustrative"] is None
    assert by_source["XAUUSD"]["fixed_direction_net_bps_at_5_illustrative"] == -4


def test_single_archive_per_source_remains_descriptive_not_replicated():
    reports = [_receipt("a", "b", 3), _receipt("c", "d", 3, instrument="WTIUSD")]
    output = bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))
    assert len(output["groups"]) == 2
    assert all(g["status"] == "DESCRIPTIVE_RECONCILED_ONLY" for g in output["groups"])


@pytest.mark.parametrize("digest", [None, "", "g" * 64, "a" * 63, "A" * 64])
def test_external_digest_must_be_well_formed(digest):
    with pytest.raises(ValueError, match="Independently retained"):
        bundle.audit_m1_precommitted_research_bundle(_three(), digest)


def test_omitted_archive_cannot_be_hidden():
    reports = _three()
    with pytest.raises(ValueError, match="differs"):
        bundle.audit_m1_precommitted_research_bundle(reports[:2], _digest(reports))


def test_rehashed_changed_archive_cannot_be_hidden():
    reports = _three()
    expected = _digest(reports)
    changed = deepcopy(reports)
    changed[0]["source"]["archive_sha256"] = "9" * 64
    _rehash(changed[0])
    with pytest.raises(ValueError, match="differs"):
        bundle.audit_m1_precommitted_research_bundle(changed, expected)


def test_tampered_original_receipt_fails_before_reconciliation():
    reports = _three()
    expected = _digest(reports)
    reports[0]["all_exploratory"]["mean_gross_bps"] = 100
    with pytest.raises(ValueError, match="fingerprint"):
        bundle.audit_m1_precommitted_research_bundle(reports, expected)


def test_cross_auditor_fixed_direction_drift_fails_closed(monkeypatch):
    reports = _three()
    original = bundle.audit_m1_paired_direction_cost_falsification

    def drift(items):
        result = deepcopy(original(items))
        result["groups"][0]["scenarios_by_illustrative_cost_bps"]["5"]["fixed_direction_net_bps"] = 99
        return result

    monkeypatch.setattr(bundle, "audit_m1_paired_direction_cost_falsification", drift)
    with pytest.raises(ValueError, match="means disagree"):
        bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))


def test_cross_auditor_source_omission_fails_closed(monkeypatch):
    reports = [_receipt("a", "b", 3), _receipt("c", "d", 3, instrument="WTIUSD")]
    original = bundle.audit_m1_cost_frontier

    def drift(items):
        result = deepcopy(original(items))
        result["groups"].pop()
        return result

    monkeypatch.setattr(bundle, "audit_m1_cost_frontier", drift)
    with pytest.raises(ValueError, match="coverage differs"):
        bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))


def test_cross_auditor_count_mismatch_fails_closed(monkeypatch):
    reports = _three()
    original = bundle.audit_m1_archive_deletion_stress

    def drift(items):
        result = deepcopy(original(items))
        result["groups"][0]["evaluated_outcome_count"] += 1
        return result

    monkeypatch.setattr(bundle, "audit_m1_archive_deletion_stress", drift)
    with pytest.raises(ValueError, match="Evaluated population"):
        bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))


def test_cross_auditor_lineage_mismatch_fails_closed(monkeypatch):
    reports = _three()
    original = bundle.audit_m1_archive_robustness

    def drift(items):
        result = deepcopy(original(items))
        result["research_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(bundle, "audit_m1_archive_robustness", drift)
    with pytest.raises(ValueError, match="lineage hashes"):
        bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))


def test_cross_auditor_deletion_disagreement_fails_closed(monkeypatch):
    reports = _three()
    original = bundle.audit_m1_archive_deletion_stress

    def drift(items):
        result = deepcopy(original(items))
        result["groups"][0]["deletion_by_whole_archive_count"]["1"][
            "scenarios_by_illustrative_cost_bps"]["5"]["min_net_bps"] = 99
        return result

    monkeypatch.setattr(bundle, "audit_m1_archive_deletion_stress", drift)
    with pytest.raises(ValueError, match="deletion auditors disagree"):
        bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))


def test_cross_auditor_safety_flag_drift_fails_closed(monkeypatch):
    reports = _three()
    original = bundle.audit_m1_cost_frontier

    def drift(items):
        result = deepcopy(original(items))
        result["trade_authorized"] = True
        return result

    monkeypatch.setattr(bundle, "audit_m1_cost_frontier", drift)
    with pytest.raises(ValueError, match="safety flags"):
        bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))


def test_all_empty_archives_remain_quarantined_without_false_success():
    reports = [_receipt("a", "b", 0), _receipt("c", "d", 0)]
    output = bundle.audit_m1_precommitted_research_bundle(reports, _digest(reports))
    assert output["groups"][0]["status"] == "INCOMPLETE_ARCHIVE_COVERAGE"
    assert output["groups"][0]["evaluated_outcome_count"] == 0
    assert output["groups"][0]["fixed_direction_net_bps_at_5_illustrative"] is None
