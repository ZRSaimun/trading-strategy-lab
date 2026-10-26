"""Synthetic regression tests for offline, source-aware round-trip net-cost audit."""
import copy
from datetime import datetime, timezone

import pytest

from app.financing_position_population import fingerprint_financing_position_population
from app.declared_roundtrip_cost_audit import (
    audit_declared_roundtrip_net, fingerprint_roundtrip_specs,
)


def fixture():
    m = {
        "protocol": "declared-financing-position-population-v1",
        "source": dict(provider="Synthetic", venue="DEMO", account_alias="paper1", settlement_currency="GBP"),
        "positions": [
            dict(position_id="p1", instrument="GOLD-CFD", opened_at=100, closed_at=400,
                 audit_asof=1000, required_rollovers=[200, 300]),
            dict(position_id="p2", instrument="SILVER-CFD", opened_at=150, closed_at=450,
                 audit_asof=1000, required_rollovers=[250]),
        ],
        "cutoffs": [500, 700],
    }
    specs = [
        dict(position_id="p1", direction="LONG", quantity="2", point_value_cash="1"),
        dict(position_id="p2", direction="SHORT", quantity="1", point_value_cash="1"),
    ]
    def receipt(pid, inst, rollover, rid, amount, revision=1, published=None, ingested=None):
        published = rollover + 1 if published is None else published
        ingested = published + 1 if ingested is None else ingested
        return dict(receipt_id=rid, provider="Synthetic", venue="DEMO",
                    instrument=inst, account_alias="paper1", position_id=pid,
                    settlement_currency="GBP", rollover_at=rollover, revision=revision,
                    published_at=published, ingested_at=ingested,
                    statement_sha256="a" * 64, amount_currency=amount)
    versions = [
        receipt("p1", "GOLD-CFD", 200, "r1", "1.00"),
        receipt("p1", "GOLD-CFD", 300, "r2", "0.50"),
        receipt("p2", "SILVER-CFD", 250, "r3", "0.25"),
    ]
    def fill(fid, pid, instrument, phase, side, when, bid, ask, price, quantity="1",
             commission="0.10", quote=None, observed=None):
        return dict(
            fill_id=fid, position_id=pid, provider="Synthetic", venue="DEMO",
            account_alias="paper1", instrument=instrument, settlement_currency="GBP",
            phase=phase, side=side, executed_at=when, received_at=when,
            quote_observed_at=when if observed is None else observed,
            quote_id=fid if quote is None else quote, bid=bid, ask=ask,
            fill_price=price, quantity=quantity, commission_cash=commission,
            execution_statement_sha256="b" * 64,
        )
    fills = [
        fill("f1", "p1", "GOLD-CFD", "ENTRY", "BUY", 100, "99", "101", "101"),
        fill("f2", "p1", "GOLD-CFD", "ENTRY", "BUY", 101, "99", "101", "101"),
        fill("f3", "p1", "GOLD-CFD", "EXIT", "SELL", 400, "109", "111", "109"),
        fill("f4", "p1", "GOLD-CFD", "EXIT", "SELL", 400, "109", "111", "109"),
        fill("f5", "p2", "SILVER-CFD", "ENTRY", "SELL", 150, "49", "51", "49"),
        fill("f6", "p2", "SILVER-CFD", "EXIT", "BUY", 450, "39", "41", "41"),
    ]
    return m, specs, versions, fills


def run(m=None, specs=None, versions=None, fills=None, cutoff=500, financing_sha=None,
        specs_sha=None, **kwargs):
    base_m, base_s, base_v, base_f = fixture()
    m = base_m if m is None else m
    specs = base_s if specs is None else specs
    versions = base_v if versions is None else versions
    fills = base_f if fills is None else fills
    financing_sha = fingerprint_financing_position_population(m) if financing_sha is None else financing_sha
    specs_sha = fingerprint_roundtrip_specs(m, specs, financing_sha) if specs_sha is None else specs_sha
    return audit_declared_roundtrip_net(
        m, versions, financing_sha, specs, specs_sha, fills,
        cutoff=cutoff, **kwargs
    )


def test_full_partial_fill_long_short_decomposition_and_net():
    result = run()
    assert result["status"] == "COMPLETE_SELF_DECLARED_ONLY"
    assert result["expected_positions"] == 2 and result["declared_fills"] == 6
    assert result["gross_mid_cash"] == "30"
    assert result["spread_cash"] == "6"
    assert result["signed_slippage_cash"] == "0"
    assert result["commission_cash"] == "0.60"
    assert result["financing_cash"] == "1.75"
    assert result["net_cash"] == "21.65"
    assert result["positions"][0]["net_cash"] == "14.10"
    assert result["positions"][1]["net_cash"] == "7.55"


def test_adverse_and_favorable_signed_slippage_no_double_spread():
    m, s, v, f = fixture()
    f[0]["fill_price"] = "101.50"  # 0.5 adverse BUY
    f[5]["fill_price"] = "40.75"   # 0.25 favorable BUY
    result = run(m, s, v, f)
    assert result["signed_slippage_cash"] == "0.25"
    assert result["net_cash"] == "21.40"


def test_commission_and_contract_multiplier_change_net_exactly():
    m, s, v, f = fixture()
    s[0]["point_value_cash"] = "2"
    f[0]["commission_cash"] = "0.15"
    result = run(m, s, v, f)
    assert result["gross_mid_cash"] == "50"
    assert result["spread_cash"] == "10"
    assert result["commission_cash"] == "0.65"
    assert result["net_cash"] == "37.60"


def test_financing_late_revision_never_rewrites_earlier_net():
    m, s, v, f = fixture()
    revision = dict(v[0], receipt_id="r1-corrected", revision=2, amount_currency="2.00",
                    published_at=600, ingested_at=650)
    v.append(revision)
    assert run(m, s, v, f, cutoff=500)["net_cash"] == "21.65"
    assert run(m, s, v, f, cutoff=700)["net_cash"] == "20.65"


def test_missing_financing_withholds_all_net_and_not_zero():
    m, s, v, f = fixture()
    result = run(m, s, v[:-1], f)
    assert result["status"] == "WITHHELD_INCOMPLETE_DECLARED_FINANCING"
    assert result["net_cash"] is None
    assert result["missing_or_unverified_positions"] == ["p2"]


def test_order_independence_deterministic_hash_and_nonmutation():
    m, s, v, f = fixture()
    original = copy.deepcopy((m, s, v, f))
    a = run(m, s, v, f)
    b = run(dict(m, positions=list(reversed(m["positions"]))),
            list(reversed(s)), list(reversed(v)), list(reversed(f)))
    assert a == b
    assert (m, s, v, f) == original


@pytest.mark.parametrize("index,change", [
    (0, {"quantity": "1.01"}),
    (0, {"fill_id": "f2"}),
    (0, {"provider": "Other"}),
    (0, {"venue": "LIVE"}),
    (0, {"account_alias": "other"}),
    (0, {"settlement_currency": "USD"}),
    (0, {"instrument": "SILVER-CFD"}),
    (0, {"side": "SELL"}),
    (0, {"phase": "EXIT"}),
    (0, {"quote_id": "f2"}),
    (0, {"bid": "102"}),
    (0, {"ask": "98"}),
    (0, {"fill_price": "0"}),
    (0, {"commission_cash": "-0.01"}),
    (0, {"quantity": "NaN"}),
    (0, {"execution_statement_sha256": "bad"}),
    (0, {"received_at": 4999}),
    (0, {"received_at": 99}),
    (0, {"quote_observed_at": 101}),
    (0, {"quote_observed_at": 90}),
    (0, {"executed_at": True}),
    (0, {"extra": "unexpected"}),
    (2, {"executed_at": 350}),
    (4, {"executed_at": 101}),
])
def test_invalid_or_cross_source_fill_fails_closed(index, change):
    m, s, v, f = fixture()
    f[index].update(change)
    with pytest.raises(ValueError):
        run(m, s, v, f)


def test_conflicting_reused_quote_id_across_positions_rejected():
    m, s, v, f = fixture()
    f[4]["quote_id"] = f[0]["quote_id"]
    with pytest.raises(ValueError, match="Conflicting"):
        run(m, s, v, f)


def test_identical_reused_quote_id_allowed():
    m, s, v, f = fixture()
    f[1]["quote_id"] = f[0]["quote_id"]
    f[1]["quote_observed_at"] = f[0]["quote_observed_at"]
    assert run(m, s, v, f)["net_cash"] == "21.65"


@pytest.mark.parametrize("mutate", [
    lambda f: f.pop(),
    lambda f: f.pop(0),
    lambda f: f.append(dict(f[0], fill_id="extra")),
    lambda f: f.__setitem__(2, dict(f[2], quantity="2")),
    lambda f: f.__setitem__(1, dict(f[1], executed_at=400)),
    lambda f: f.__setitem__(5, dict(f[5], executed_at=400)),
])
def test_missing_extra_or_wrongly_ordered_partial_fill_rejected(mutate):
    m, s, v, f = fixture()
    mutate(f)
    with pytest.raises(ValueError):
        run(m, s, v, f)


@pytest.mark.parametrize("mutate", [
    lambda s: s.pop(),
    lambda s: s.append(dict(s[0])),
    lambda s: s[0].update(quantity="0"),
    lambda s: s[0].update(direction="HEDGE"),
    lambda s: s[0].update(point_value_cash="1e2"),
    lambda s: s[0].update(point_value_cash="0"),
    lambda s: s[0].update(extra=1),
])
def test_bad_specification_population_rejected(mutate):
    m, s, v, f = fixture()
    mutate(s)
    with pytest.raises(ValueError):
        run(m, s, v, f)


def test_stale_specification_digest_rejected():
    m, s, v, f = fixture()
    fm = fingerprint_financing_position_population(m)
    digest = fingerprint_roundtrip_specs(m, s, fm)
    s[0]["quantity"] = "3"
    with pytest.raises(ValueError, match="digest mismatch"):
        run(m, s, v, f, financing_sha=fm, specs_sha=digest)


@pytest.mark.parametrize("cutoff,age", [(499, 5), (800, 5), (500, -1), (500, 61), (500, True)])
def test_cutoff_or_age_policy_invalid(cutoff, age):
    with pytest.raises(ValueError):
        run(cutoff=cutoff, max_quote_age_seconds=age)


def test_stale_quote_and_future_receipt_rejected():
    m, s, v, f = fixture()
    f[1]["quote_observed_at"] = 100
    with pytest.raises(ValueError):
        run(m, s, v, f, max_quote_age_seconds=0)
    f[1]["quote_observed_at"] = 101
    f[1]["received_at"] = 600
    with pytest.raises(ValueError):
        run(m, s, v, f, cutoff=500)


def test_eight_year_synthetic_cost_census_not_eight_year_profits():
    m, s, v, f = fixture()
    m["positions"], s, v, f = [], [], [], []
    for year in range(2019, 2027):
        stamp = int(datetime(year, 1, 10, tzinfo=timezone.utc).timestamp())
        pid = f"y{year}"
        m["positions"].append(dict(position_id=pid, instrument="GOLD-CFD",
                                   opened_at=stamp, closed_at=stamp + 200,
                                   audit_asof=1800000000, required_rollovers=[stamp + 100]))
        s.append(dict(position_id=pid, direction="LONG", quantity="1", point_value_cash="1"))
        v.append(dict(receipt_id=f"r{year}", provider="Synthetic", venue="DEMO",
                      account_alias="paper1", instrument="GOLD-CFD", position_id=pid,
                      settlement_currency="GBP", rollover_at=stamp + 100,
                      revision=1, published_at=stamp + 101, ingested_at=stamp + 102,
                      statement_sha256="a" * 64, amount_currency="0.25"))
        for phase, side, at, bid, ask, price in [
            ("ENTRY", "BUY", stamp, "99", "101", "101"),
            ("EXIT", "SELL", stamp + 200, "109", "111", "109"),
        ]:
            f.append(dict(fill_id=f"{pid}-{phase}", position_id=pid,
                          provider="Synthetic", venue="DEMO", account_alias="paper1",
                          instrument="GOLD-CFD", settlement_currency="GBP",
                          phase=phase, side=side, executed_at=at, received_at=at,
                          quote_observed_at=at, quote_id=f"{pid}-{phase}",
                          bid=bid, ask=ask, fill_price=price, quantity="1",
                          commission_cash="0.10", execution_statement_sha256="b" * 64))
    m["cutoffs"] = [1800000000 - 1000]
    report = run(m, s, v, f, cutoff=m["cutoffs"][0])
    assert report["expected_positions"] == 8
    assert report["net_cash"] == "60.40"
    f.pop()
    with pytest.raises(ValueError):
        run(m, s, v, f, cutoff=m["cutoffs"][0])


def test_never_assert_authenticity_profitability_or_execution():
    report = run()
    for key in ("source_authenticated", "real_execution_costs_verified",
                "contract_multipliers_verified", "untouched_holdout_verified",
                "verified_profitability", "may_execute_order"):
        assert report[key] is False
