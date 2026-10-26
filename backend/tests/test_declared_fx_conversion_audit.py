"""Synthetic offline point-in-time FX cost translation regressions."""
import copy

import pytest

from app.financing_position_population import fingerprint_financing_position_population
from app.declared_roundtrip_cost_audit import fingerprint_roundtrip_specs
from app.declared_fx_conversion_audit import (
    audit_declared_roundtrip_fx, fingerprint_fx_conversion_policy,
)
from test_declared_roundtrip_cost_audit import fixture


def inputs():
    m, specs, versions, fills = fixture()
    policy = dict(fx_provider="SyntheticFX", fx_venue="DEMO", reporting_currency="USD",
                  max_quote_age_seconds=5)
    def quote(pid, when, bid, ask):
        return dict(position_id=pid, account_alias="paper1", fx_provider="SyntheticFX",
                    fx_venue="DEMO", base_currency="GBP", quote_currency="USD",
                    quote_id=f"fx-{pid}", observed_at=when, received_at=when,
                    bid=bid, ask=ask, source_statement_sha256="c" * 64)
    quotes = [quote("p1", 400, "1.20", "1.22"), quote("p2", 450, "1.19", "1.21")]
    return m, specs, versions, fills, policy, quotes


def run(data=None, *, cutoff=500, policy_sha=None, specs_sha=None):
    m, specs, versions, fills, policy, quotes = inputs() if data is None else data
    finance_sha = fingerprint_financing_position_population(m)
    specs_sha = fingerprint_roundtrip_specs(m, specs, finance_sha) if specs_sha is None else specs_sha
    policy_sha = fingerprint_fx_conversion_policy(m, policy, finance_sha, specs_sha) if policy_sha is None else policy_sha
    return audit_declared_roundtrip_fx(
        m, versions, finance_sha, specs, specs_sha, fills, cutoff=cutoff,
        fx_policy=policy, expected_fx_policy_sha256=policy_sha, fx_quotes=quotes,
    )


def test_complete_fx_valuation_exact_and_no_double_spread():
    result = run()
    assert result["status"] == "COMPLETE_SELF_DECLARED_ONLY"
    assert result["expected_positions"] == 2
    assert result["positions"][0]["net_reporting_cash"] == "16.9200"
    assert result["positions"][1]["net_reporting_cash"] == "8.9845"
    assert result["net_reporting_cash"] == "25.9045"
    assert result["fx_half_spread_cost_reporting_cash"] == "0.2165"
    assert result["mid_reporting_cash"] == "26.1210"


def test_negative_cash_liability_uses_ask_not_bid():
    data = inputs()
    data[3][5]["fill_price"] = "61"  # synthetic adverse short exit
    result = run(data)
    assert result["positions"][1]["settlement_net_cash"] == "-12.45"
    assert result["positions"][1]["net_reporting_cash"] == "-15.0645"
    assert result["positions"][1]["fx_half_spread_cost_reporting_cash"] == "0.1245"
    assert result["net_reporting_cash"] == "1.8555"


def test_asof_financing_revision_changes_net_not_close_time_fx():
    data = inputs()
    data[2].append(dict(data[2][0], receipt_id="r1-corrected", revision=2,
                        amount_currency="2.00", published_at=600, ingested_at=650))
    early = run(data, cutoff=500)
    late = run(data, cutoff=700)
    assert early["net_reporting_cash"] == "25.9045"
    assert late["net_reporting_cash"] == "24.7045"
    assert early["fx_quote_declaration_sha256"] == late["fx_quote_declaration_sha256"]


def test_missing_financing_withholds_all_reporting_net():
    data = inputs()
    data[2].pop()
    report = run(data)
    assert report["status"] == "WITHHELD_INCOMPLETE_UPSTREAM_COSTS"
    assert report["net_reporting_cash"] is None
    assert report["may_execute_order"] is False


def test_reordered_declarations_are_deterministic_and_nonmutating():
    data = inputs()
    original = copy.deepcopy(data)
    first = run(data)
    for index in (1, 2, 3, 5):
        data[index].reverse()
    second = run(data)
    assert first == second
    assert original[0] == data[0]


def test_policy_freeze_binds_currency_source_age_and_close_anchors():
    data = inputs()
    finance_sha = fingerprint_financing_position_population(data[0])
    specs_sha = fingerprint_roundtrip_specs(data[0], data[1], finance_sha)
    digest = fingerprint_fx_conversion_policy(data[0], data[4], finance_sha, specs_sha)
    data[4]["max_quote_age_seconds"] = 6
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data, policy_sha=digest)


@pytest.mark.parametrize("index,field,value", [
    (0, "fx_provider", "Other"),
    (0, "fx_venue", "LIVE"),
    (0, "account_alias", "other"),
    (0, "base_currency", "USD"),
    (0, "quote_currency", "GBP"),
    (0, "quote_id", ""),
    (0, "source_statement_sha256", "bad"),
    (0, "observed_at", 401),
    (0, "observed_at", 394),
    (0, "received_at", 401),
    (0, "received_at", 399),
    (0, "observed_at", True),
    (0, "bid", "0"),
    (0, "bid", "NaN"),
    (0, "bid", "1e2"),
    (0, "bid", "1.230"),
    (0, "ask", "0"),
    (0, "ask", "1.190"),
    (0, "ask", "1.00000000001"),
    (0, "extra", "surprise"),
])
def test_invalid_fx_evidence_fails_closed(index, field, value):
    data = inputs()
    data[5][index][field] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("mutation", [
    lambda quotes: quotes.pop(),
    lambda quotes: quotes.append(copy.deepcopy(quotes[0])),
    lambda quotes: quotes.__setitem__(1, dict(quotes[1], position_id="unknown")),
    lambda quotes: quotes.__setitem__(1, dict(quotes[1], position_id="p1")),
    lambda quotes: quotes.__setitem__(1, dict(quotes[1], quote_id="fx-p1")),
])
def test_quote_population_and_conflicting_quote_ids_fail_closed(mutation):
    data = inputs()
    mutation(data[5])
    with pytest.raises(ValueError):
        run(data)


def test_reused_identical_quote_id_still_fails_when_stale_for_other_position():
    data = inputs()
    data[5][1] = dict(data[5][0], position_id="p2")
    with pytest.raises(ValueError, match="Stale"):
        run(data)


@pytest.mark.parametrize("change", [
    {"reporting_currency": "GBP"},
    {"reporting_currency": "USDT"},
    {"fx_provider": ""},
    {"max_quote_age_seconds": True},
    {"max_quote_age_seconds": 3601},
    {"max_quote_age_seconds": -1},
    {"extra": 1},
])
def test_invalid_fx_policy_rejected(change):
    data = inputs()
    data[4].update(change)
    with pytest.raises(ValueError):
        run(data)


def test_no_authentication_profit_or_execution_claims():
    result = run()
    for key in ("source_authenticated", "fx_quotes_authenticated",
                "real_execution_costs_verified", "untouched_holdout_verified",
                "verified_profitability", "may_execute_order"):
        assert result[key] is False
