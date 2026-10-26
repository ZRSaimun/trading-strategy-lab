"""End-to-end synthetic financing/fill/FX/rounding integration regressions."""
import pytest

from app.financing_position_population import fingerprint_financing_position_population
from app.declared_roundtrip_cost_audit import fingerprint_roundtrip_specs
from app.declared_fx_conversion_audit import fingerprint_fx_conversion_policy
from app.declared_fx_rounding_sensitivity import (
    audit_declared_fx_rounding, fingerprint_fx_rounding_policy,
)
from test_declared_fx_conversion_audit import inputs


def run(data=None):
    m, specs, versions, fills, fx_policy, quotes = inputs() if data is None else data
    finance_sha = fingerprint_financing_position_population(m)
    specs_sha = fingerprint_roundtrip_specs(m, specs, finance_sha)
    fx_sha = fingerprint_fx_conversion_policy(m, fx_policy, finance_sha, specs_sha)
    policy = {"reporting_minor_units": 2, "rounding_mode": "HALF_EVEN"}
    rounding_sha = fingerprint_fx_rounding_policy(fx_sha, 500, policy)
    return audit_declared_fx_rounding(
        m, versions, finance_sha, specs, specs_sha, fills, cutoff=500,
        fx_policy=fx_policy, expected_fx_policy_sha256=fx_sha, fx_quotes=quotes,
        rounding_policy=policy, expected_rounding_policy_sha256=rounding_sha,
    )


def test_real_upstream_synthetic_cost_and_fx_pipeline():
    result = run()
    assert result["status"] == "COMPLETE_HYPOTHETICAL_ONLY"
    assert result["unrounded_net_reporting_cash"] == "25.9045"
    assert result["rounded_net_reporting_cash"] == "25.90"
    assert result["rounding_delta_reporting_cash"] == "-0.0045"
    assert [p["rounded_cash"] for p in result["positions"]] == ["16.92", "8.98"]
    assert result["may_execute_order"] is False


def test_missing_financing_withholds_rounding_population():
    data = inputs()
    data[2].pop()
    result = run(data)
    assert result["status"] == "WITHHELD_INCOMPLETE_UPSTREAM_FX"
    assert result["rounded_net_reporting_cash"] is None


def test_cross_source_fx_quote_rejected_by_actual_upstream():
    data = inputs()
    data[5][0]["account_alias"] = "wrong"
    with pytest.raises(ValueError, match="Cross-source"):
        run(data)
