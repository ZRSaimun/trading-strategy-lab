"""Synthetic cross-position financing census regressions; no broker access."""

import copy
from datetime import datetime, timezone

import pytest

from app.financing_position_population import (
    audit_financing_position_population,
    fingerprint_financing_position_population,
)


def manifest():
    return dict(
        protocol="declared-financing-position-population-v1",
        source=dict(provider="Synthetic", venue="DEMO", account_alias="paper-1", settlement_currency="GBP"),
        positions=[
            dict(position_id="p1", instrument="XAUUSD-CFD", opened_at=100, closed_at=400,
                 audit_asof=1000, required_rollovers=[200, 300]),
            dict(position_id="p2", instrument="XAGUSD-CFD", opened_at=150, closed_at=450,
                 audit_asof=1000, required_rollovers=[250, 350]),
        ],
        cutoffs=[500, 700, 900],
    )


def receipt(rid, position, instrument, rollover, amount, revision=1, published=None, ingested=None):
    published = rollover + 5 if published is None else published
    ingested = published + 5 if ingested is None else ingested
    return dict(receipt_id=rid, provider="Synthetic", venue="DEMO", instrument=instrument,
                account_alias="paper-1", position_id=position, settlement_currency="GBP",
                rollover_at=rollover, revision=revision, published_at=published, ingested_at=ingested,
                statement_sha256="a" * 64, amount_currency=amount)


def rows():
    return [receipt("a", "p1", "XAUUSD-CFD", 200, "1.00"),
            receipt("b", "p1", "XAUUSD-CFD", 300, "0.50"),
            receipt("c", "p2", "XAGUSD-CFD", 250, "-0.25"),
            receipt("d", "p2", "XAGUSD-CFD", 350, "0.05")]


def run(m=None, versions=None, digest=None):
    m = manifest() if m is None else m
    versions = rows() if versions is None else versions
    return audit_financing_position_population(
        m, versions, fingerprint_financing_position_population(m) if digest is None else digest)


def test_exact_signed_cents_across_positions_and_instruments():
    result = run()
    assert [r["total_financing_currency"] for r in result["snapshots"]] == ["1.30"] * 3
    assert all(s["status"] == "COMPLETE_SELF_DECLARED_ONLY" for s in result["snapshots"])
    assert result["expected_positions"] == 2 and result["declared_receipt_versions"] == 4
    assert result["snapshots"][0]["positions"][1]["declared_total_currency"] == "-0.20"


def test_late_correction_never_rewrites_earlier_cutoff():
    amended = rows() + [receipt("a2", "p1", "XAUUSD-CFD", 200, "2.00", 2, 600, 650)]
    result = run(versions=amended)
    assert [r["total_financing_currency"] for r in result["snapshots"]] == ["1.30", "2.30", "2.30"]
    assert result["snapshots"][0]["positions"][0]["selected_revisions"][0]["revision"] == 1
    assert result["snapshots"][1]["positions"][0]["selected_revisions"][0]["revision"] == 2


def test_late_first_receipt_withholds_entire_portfolio_not_only_position():
    changed = [dict(row, published_at=600, ingested_at=650) if row["receipt_id"] == "a" else row
               for row in rows()]
    result = run(versions=changed)
    assert result["snapshots"][0]["status"] == "WITHHELD_INCOMPLETE_DECLARED_FINANCING"
    assert result["snapshots"][0]["total_financing_currency"] is None
    assert result["snapshots"][0]["missing_or_unverified_positions"] == ["p1"]
    assert result["snapshots"][1]["total_financing_currency"] == "1.30"


def test_missing_position_receipts_withhold_full_total():
    result = run(versions=rows()[:2])
    assert all(s["total_financing_currency"] is None for s in result["snapshots"])
    assert all(s["missing_or_unverified_positions"] == ["p2"] for s in result["snapshots"])


def test_empty_rollover_schedule_does_not_imply_free_financing():
    m = manifest()
    m["positions"][1]["required_rollovers"] = []
    result = run(m, versions=rows()[:2])
    assert result["snapshots"][0]["positions"][1]["status"] == "NO_DUE_DECLARED_ROLLOVERS"
    assert result["snapshots"][0]["total_financing_currency"] is None


def test_explicit_zero_financing_is_different_from_absent_receipt():
    changed = [dict(row, amount_currency="0") for row in rows()]
    result = run(versions=changed)
    assert result["snapshots"][0]["total_financing_currency"] == "0.00"


def test_order_independence_nonmutation_and_fingerprints():
    m, v = manifest(), rows()
    before = copy.deepcopy((m, v))
    a = run(m, v)
    b = run(dict(m, positions=list(reversed(m["positions"]))), list(reversed(v)))
    assert a == b
    assert (m, v) == before
    assert len(a["declaration_sha256"]) == 64


def test_receipt_change_updates_declaration_digest_but_not_membership_digest():
    a = run()
    changed = [dict(rows()[0], amount_currency="1.01"), *rows()[1:]]
    b = run(versions=changed)
    assert a["expected_manifest_sha256"] == b["expected_manifest_sha256"]
    assert a["declaration_sha256"] != b["declaration_sha256"]


def test_changed_expected_position_fails_stale_digest():
    m = manifest()
    digest = fingerprint_financing_position_population(m)
    m["positions"][0]["required_rollovers"] = [200]
    with pytest.raises(ValueError, match="digest mismatch"):
        run(m, versions=rows(), digest=digest)


def test_duplicate_cross_position_receipt_id_rejected():
    v = rows()
    v[2]["receipt_id"] = v[0]["receipt_id"]
    with pytest.raises(ValueError, match="cross-position"):
        run(versions=v)


def test_unknown_position_and_missing_receipt_id_rejected():
    for changed in (dict(rows()[0], position_id="p3"),
                    {k: v for k, v in rows()[0].items() if k != "receipt_id"}):
        with pytest.raises(ValueError):
            run(versions=[changed, *rows()[1:]])


@pytest.mark.parametrize("change", [
    {"provider": "Other"}, {"venue": "LIVE"}, {"account_alias": "other"},
    {"settlement_currency": "USD"}, {"instrument": "XAGUSD-CFD"},
    {"statement_sha256": "bad"}, {"amount_currency": "NaN"},
    {"published_at": 1000}, {"revision": 2}, {"extra": "unexpected"},
])
def test_cross_source_or_malformed_receipt_rejected(change):
    with pytest.raises(ValueError):
        run(versions=[dict(rows()[0], **change), *rows()[1:]])


@pytest.mark.parametrize("mutation", [
    lambda m: m["positions"].append(copy.deepcopy(m["positions"][0])),
    lambda m: m["positions"].clear(),
    lambda m: m["positions"][0].update(position_id="bad/id"),
    lambda m: m["positions"][0].update(opened_at=True),
    lambda m: m["positions"][0].update(closed_at=100),
    lambda m: m["positions"][0].update(required_rollovers=[300, 200]),
    lambda m: m["positions"][0].update(required_rollovers=[200, 200]),
    lambda m: m["positions"][0].update(required_rollovers=[200, 400]),
    lambda m: m["positions"][0].update(extra=1),
    lambda m: m["source"].update(settlement_currency="GB"),
    lambda m: m["source"].update(extra=1),
    lambda m: m.update(protocol="unknown"),
    lambda m: m.update(extra=1),
    lambda m: m.update(cutoffs=[449]),
    lambda m: m.update(cutoffs=[1001]),
    lambda m: m.update(cutoffs=[700, 500]),
    lambda m: m.update(cutoffs=[500, 500]),
    lambda m: m.update(cutoffs=[True]),
    lambda m: m.update(cutoffs=[]),
])
def test_malformed_or_unbounded_expected_population_rejected(mutation):
    m = manifest()
    mutation(m)
    with pytest.raises(ValueError):
        fingerprint_financing_position_population(m)


def test_manifest_caps_and_receipt_caps():
    m = manifest()
    m["positions"] = [dict(m["positions"][0], position_id=f"p{i}") for i in range(257)]
    with pytest.raises(ValueError, match="bounded"):
        fingerprint_financing_position_population(m)
    with pytest.raises(ValueError, match="bounded"):
        run(versions=rows() * 2501)


def test_eight_year_synthetic_closed_position_census_and_missing_year():
    stamps = [int(datetime(y, 1, 10, tzinfo=timezone.utc).timestamp()) for y in range(2019, 2027)]
    cutoff = stamps[-1] + 400000
    m = manifest()
    m["positions"] = [dict(position_id=f"year-{year}", instrument="XAUUSD-CFD",
                            opened_at=stamp - 100, closed_at=stamp + 100,
                            audit_asof=cutoff + 100, required_rollovers=[stamp])
                      for year, stamp in zip(range(2019, 2027), stamps)]
    m["cutoffs"] = [cutoff]
    v = [receipt(f"r-{year}", f"year-{year}", "XAUUSD-CFD", stamp, "0.01",
                 published=stamp + 1, ingested=stamp + 2)
         for year, stamp in zip(range(2019, 2027), stamps)]
    assert run(m, v)["snapshots"][0]["total_financing_currency"] == "0.08"
    assert run(m, v[:-1])["snapshots"][0]["total_financing_currency"] is None


def test_report_never_claims_authenticated_broker_costs_or_profit():
    report = run()
    for key in ("source_authenticated", "complete_broker_position_population_verified",
                "independent_preregistration_verified", "real_execution_costs_verified",
                "verified_profitability", "may_execute_order"):
        assert report[key] is False
