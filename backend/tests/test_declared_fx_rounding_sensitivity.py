"""Synthetic exact-decimal regressions for hypothetical FX rounding."""
import copy
from decimal import Decimal

import pytest

from app import declared_fx_rounding_sensitivity as mod


def upstream(values=("0.005", "0.005")):
    return dict(
        protocol="declared-roundtrip-point-in-time-fx-v1",
        status="COMPLETE_SELF_DECLARED_ONLY",
        fx_policy_sha256="a" * 64, cutoff=500,
        may_execute_order=False, source_authenticated=False,
        fx_quotes_authenticated=False, expected_positions=len(values),
        reporting_currency="USD", fx_quote_declaration_sha256="b" * 64,
        positions=[dict(position_id=f"p{i}", net_reporting_cash=x)
                   for i, x in enumerate(values)],
        net_reporting_cash=format(sum((Decimal(x) for x in values), Decimal(0)), "f"),
    )


def run(monkeypatch, values=("0.005", "0.005"), policy=None, source=None, sha=None):
    monkeypatch.setattr(
        mod, "audit_declared_roundtrip_fx",
        lambda *a, **k: copy.deepcopy(source if source is not None else upstream(values)),
    )
    policy = policy if policy is not None else dict(
        reporting_minor_units=2, rounding_mode="HALF_EVEN",
    )
    digest = mod.fingerprint_fx_rounding_policy("a" * 64, 500, policy) if sha is None else sha
    return mod.audit_declared_fx_rounding(
        None, None, None, None, None, None, cutoff=500,
        fx_policy=None, expected_fx_policy_sha256="a" * 64,
        fx_quotes=None, rounding_policy=policy,
        expected_rounding_policy_sha256=digest,
    )


def test_per_position_vs_aggregate_half_even(monkeypatch):
    result = run(monkeypatch)
    assert result["rounded_net_reporting_cash"] == "0.00"
    assert result["aggregate_only_rounded_cash"] == "0.01"
    assert result["per_position_minus_aggregate_rounded_cash"] == "-0.01"
    assert result["rounding_delta_reporting_cash"] == "-0.010"
    assert result["may_execute_order"] is False


def test_half_up_ties_away_from_zero(monkeypatch):
    result = run(monkeypatch, ("0.005", "-0.005"),
                 dict(reporting_minor_units=2, rounding_mode="HALF_UP"))
    assert [p["rounded_cash"] for p in result["positions"]] == ["0.01", "-0.01"]
    assert result["rounded_net_reporting_cash"] == "0.00"


def test_toward_zero_negative_and_zero_minor_units(monkeypatch):
    result = run(monkeypatch, ("1.9", "-1.9"),
                 dict(reporting_minor_units=0, rounding_mode="TOWARD_ZERO"))
    assert [p["rounded_cash"] for p in result["positions"]] == ["1", "-1"]


def test_reordered_upstream_rows_deterministic(monkeypatch):
    original = upstream(("0.005", "-0.006", "1.234"))
    first = run(monkeypatch, source=original)
    reordered = copy.deepcopy(original)
    reordered["positions"].reverse()
    assert first == run(monkeypatch, source=reordered)


@pytest.mark.parametrize("change", [
    {"reporting_minor_units": -1}, {"reporting_minor_units": 7},
    {"reporting_minor_units": True}, {"reporting_minor_units": 2.0},
    {"rounding_mode": "BANKERS"}, {"rounding_mode": 2}, {"extra": True},
])
def test_invalid_policy_rejected(monkeypatch, change):
    policy = dict(reporting_minor_units=2, rounding_mode="HALF_EVEN")
    policy.update(change)
    with pytest.raises(ValueError):
        run(monkeypatch, policy=policy)


def test_changed_policy_requires_new_digest(monkeypatch):
    old = mod.fingerprint_fx_rounding_policy(
        "a" * 64, 500, dict(reporting_minor_units=2, rounding_mode="HALF_EVEN"),
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        run(monkeypatch, policy=dict(reporting_minor_units=3, rounding_mode="HALF_EVEN"), sha=old)


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(net_reporting_cash="0.02"),
    lambda x: x["positions"].pop(),
    lambda x: x["positions"].__setitem__(1, dict(x["positions"][1], position_id="p0")),
    lambda x: x["positions"][0].update(net_reporting_cash="NaN"),
    lambda x: x["positions"][0].update(net_reporting_cash="1e99"),
    lambda x: x.update(fx_policy_sha256="b" * 64),
    lambda x: x.update(may_execute_order=True),
    lambda x: x.update(source_authenticated=True),
    lambda x: x.update(cutoff=501),
    lambda x: x.update(protocol="unknown"),
])
def test_corrupt_upstream_report_rejected(monkeypatch, mutate):
    data = upstream()
    mutate(data)
    with pytest.raises(ValueError):
        run(monkeypatch, source=data)


def test_incomplete_upstream_withholds(monkeypatch):
    result = run(monkeypatch, source=dict(status="WITHHELD_INCOMPLETE_UPSTREAM_COSTS"))
    assert result["status"] == "WITHHELD_INCOMPLETE_UPSTREAM_FX"
    assert result["rounded_net_reporting_cash"] is None


def test_many_synthetic_positions_conserve_cash(monkeypatch):
    values = tuple(f"{i % 17}.{i % 10000:04d}" for i in range(256))
    result = run(monkeypatch, values)
    raw = sum((Decimal(x) for x in values), Decimal(0))
    rounded = sum((Decimal(p["rounded_cash"]) for p in result["positions"]), Decimal(0))
    assert rounded - raw == Decimal(result["rounding_delta_reporting_cash"])
    assert rounded == Decimal(result["rounded_net_reporting_cash"])
    assert result["expected_positions"] == 256


def test_flags_never_claim_real_settlement_or_profit(monkeypatch):
    result = run(monkeypatch)
    for flag in ("source_authenticated", "broker_settlement_verified",
                 "untouched_holdout_verified", "verified_profitability",
                 "may_execute_order"):
        assert result[flag] is False
