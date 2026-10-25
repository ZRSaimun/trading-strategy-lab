"""Synthetic, offline tests; not observed market prices or broker evidence."""
from copy import deepcopy
import pytest
from app.asof_feature_vintage_audit import (
    audit_asof_feature_vintages, fingerprint_feature_vintages,
)

T = 1800000000
SHA = "a" * 64


def sample():
    return dict(
        protocol="asof-feature-vintage-manifest-v1",
        decision_source=dict(provider="synthetic", instrument="XAUUSD", venue="fixture",
                             archive_sha256=SHA, price_side="BID"),
        decisions=[dict(decision_id="d1", at=T + 30), dict(decision_id="d2", at=T + 70)],
        series=[dict(series_id="cpi", provider="synthetic", instrument="US-CPI",
                     venue="fixture", archive_sha256="b" * 64, max_age_seconds=120)],
        vintages=[dict(series_id="cpi", observation_at=T, available_at=T + 10,
                       revision=0, value_sha256="1" * 64),
                  dict(series_id="cpi", observation_at=T, available_at=T + 50,
                       revision=1, value_sha256="2" * 64)],
    )


def run(m):
    return audit_asof_feature_vintages(m, fingerprint_feature_vintages(m))


def test_original_then_revised_vintage_selected_as_of_decision():
    result = run(sample())
    assert result["status"] == "COMPLETE_DECLARED_ONLY"
    assert [r["revision"] for r in result["selections"]] == [0, 1]
    assert [r["value_sha256"] for r in result["selections"]] == ["1" * 64, "2" * 64]
    assert result["independent_source_authentication"] is False
    assert result["may_execute_order"] is False


def test_newer_observation_not_yet_published_keeps_older_vintage():
    m = sample()
    m["vintages"].append(dict(series_id="cpi", observation_at=T + 20,
                              available_at=T + 60, revision=0, value_sha256="3" * 64))
    rows = run(m)["selections"]
    assert rows[0]["observation_at"] == T
    assert rows[1]["observation_at"] == T + 20
    assert rows[1]["revision"] == 0


def test_late_revision_to_old_observation_does_not_override_new_observation():
    m = sample()
    m["vintages"].append(dict(series_id="cpi", observation_at=T + 20,
                              available_at=T + 25, revision=0, value_sha256="3" * 64))
    rows = run(m)["selections"]
    assert rows[0]["observation_at"] == T + 20
    assert rows[1]["observation_at"] == T + 20


def test_exact_publication_boundary_is_available():
    m = sample()
    m["decisions"][0]["at"] = T + 10
    assert run(m)["selections"][0]["revision"] == 0


def test_one_second_before_publication_is_withheld():
    m = sample()
    m["decisions"][0]["at"] = T + 9
    r = run(m)
    assert r["status"] == "WITHHELD_MISSING_OR_STALE"
    assert r["selections"][0]["status"] == "MISSING_ASOF"
    assert "value_sha256" not in r["selections"][0]


def test_stale_series_withholds_hash_and_never_implies_free_data():
    m = sample()
    m["series"][0]["max_age_seconds"] = 29
    rows = run(m)["selections"]
    assert rows[0]["status"] == "STALE_ASOF"
    assert rows[1]["status"] == "STALE_ASOF"
    assert all("value_sha256" not in row for row in rows)


def test_exact_max_age_is_eligible():
    m = sample()
    m["series"][0]["max_age_seconds"] = 30
    assert run(m)["selections"][0]["status"] == "SELECTED"


def test_no_vintages_does_not_fabricate_zero_values():
    m = sample()
    m["vintages"] = []
    r = run(m)
    assert r["counts"]["MISSING_ASOF"] == 2
    assert r["status"].startswith("WITHHELD")


def test_order_invariant_receipt_and_result_without_mutation():
    m = sample()
    before = deepcopy(m)
    first = run(m)
    m["decisions"].reverse()
    m["vintages"].reverse()
    assert run(m) == first
    assert before["vintages"] == list(reversed(m["vintages"]))


def test_tampering_after_receipt_is_rejected():
    m = sample()
    digest = fingerprint_feature_vintages(m)
    m["vintages"][0]["value_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="mismatch"):
        audit_asof_feature_vintages(m, digest)


def test_source_identity_changes_digest():
    m = sample()
    original = fingerprint_feature_vintages(m)
    m["series"][0]["provider"] = "another"
    assert fingerprint_feature_vintages(m) != original


@pytest.mark.parametrize("change", [
    lambda m: m["vintages"].append(deepcopy(m["vintages"][0])),
    lambda m: m["vintages"][1].update(revision=2),
    lambda m: m["vintages"][1].update(available_at=T + 10),
    lambda m: m["vintages"][0].update(available_at=T - 1),
    lambda m: m["vintages"][0].update(revision=True),
    lambda m: m["vintages"][0].update(series_id="foreign"),
    lambda m: m["vintages"][0].update(value_sha256="bad"),
    lambda m: m["vintages"][0].update(value="100"),
    lambda m: m["decisions"][0].update(at=True),
    lambda m: m["decisions"][1].update(decision_id="d1"),
    lambda m: m["series"][0].update(max_age_seconds=-1),
    lambda m: m["series"][0].update(max_age_seconds=True),
    lambda m: m["series"][0].update(archive_sha256="bad"),
    lambda m: m["decision_source"].update(price_side="UNKNOWN"),
])
def test_invalid_metadata_fails_closed(change):
    m = sample()
    change(m)
    with pytest.raises(ValueError):
        run(m)


def test_missing_series_identity_rejected():
    m = sample()
    m["series"].append(deepcopy(m["series"][0]))
    with pytest.raises(ValueError, match="series ID"):
        run(m)


def test_multiple_required_series_and_partial_coverage():
    m = sample()
    m["series"].append(dict(series_id="yields", provider="fixture", instrument="US10Y",
                            venue="fixture", archive_sha256="c" * 64, max_age_seconds=100))
    r = run(m)
    assert r["counts"]["SELECTED"] == 2
    assert r["counts"]["MISSING_ASOF"] == 2
    assert r["status"] == "WITHHELD_MISSING_OR_STALE"


def test_future_only_vintage_not_leaked_into_earlier_decisions():
    m = sample()
    m["vintages"] = [dict(series_id="cpi", observation_at=T + 100,
                          available_at=T + 101, revision=0, value_sha256="f" * 64)]
    r = run(m)
    assert r["counts"]["SELECTED"] == 0
    assert all("value_sha256" not in row for row in r["selections"])


def test_invalid_expected_digest_fails_closed():
    with pytest.raises(ValueError, match="Expected manifest"):
        audit_asof_feature_vintages(sample(), "wrong")


def test_duplicate_published_vintages_with_different_revisions_need_strict_clock():
    m = sample()
    m["vintages"][1]["available_at"] = m["vintages"][0]["available_at"]
    with pytest.raises(ValueError, match="strictly increasing"):
        run(m)
