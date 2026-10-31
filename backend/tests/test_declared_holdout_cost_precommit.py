"""Synthetic-only tests for outcome-free declared cost scenario precommitment."""
import copy

import pytest

from app.declared_holdout_cost_precommit import (
    prepare_declared_holdout_row_cost_scenario_set_sha256 as prepare,
    require_declared_holdout_row_cost_scenario_set_sha256 as require,
)
from test_declared_holdout_cost_attribution import _fixture
from test_declared_holdout_row_cost_stress import _audit, _scenario


def test_precommit_matches_released_audit_without_outcomes():
    data = _fixture()
    scenario = _scenario(data, per_row={
        0: {"spread_extra_cash": "0.2000"},
        1: {"financing_extra_cash": "0.3000"},
    })
    digest = prepare(data[0], data[1], [scenario])
    assert digest == _audit(data, [scenario])["scenario_set_sha256"]
    assert require(data[0], data[1], [scenario], digest) == digest


def test_precommit_canonicalizes_scenario_and_adjustment_order():
    data = _fixture()
    scenarios = [
        _scenario(data, "alpha", {0: {"spread_extra_cash": "0.1000"}}),
        _scenario(data, "beta", {1: {"slippage_extra_cash": "0.2000"}}),
    ]
    original = copy.deepcopy(scenarios)
    digest = prepare(data[0], data[1], scenarios)
    reversed_scenarios = copy.deepcopy(scenarios)[::-1]
    for scenario in reversed_scenarios:
        scenario["adjustments"].reverse()
    assert digest == prepare(data[0], data[1], reversed_scenarios)
    assert scenarios == original


def test_precommit_binds_component_and_exact_cash_text():
    data = _fixture()
    a = _scenario(data, per_row={0: {"spread_extra_cash": "0.1"}})
    b = _scenario(data, per_row={0: {"spread_extra_cash": "0.1000"}})
    c = _scenario(data, per_row={0: {"slippage_extra_cash": "0.1"}})
    assert len({prepare(data[0], data[1], [x]) for x in (a, b, c)}) == 3


def test_precommit_is_independent_of_outcomes_and_available_for_small_holdout():
    data = _fixture(29)
    scenario = _scenario(data)
    digest = prepare(data[0], data[1], [scenario])
    changed = copy.deepcopy(data)
    changed[3][0]["gross_cash"] = "-900.0000"
    assert digest == prepare(changed[0], changed[1], [scenario])
    assert len(digest) == 64


def test_expected_digest_mismatch_or_invalid_digest_fails_closed():
    data = _fixture()
    scenario = _scenario(data)
    digest = prepare(data[0], data[1], [scenario])
    with pytest.raises(ValueError, match="mismatch"):
        require(data[0], data[1], [scenario], "0" * 64 if digest != "0" * 64 else "1" * 64)
    for invalid in ("A" * 64, "0" * 63, None, 0):
        with pytest.raises(ValueError, match="Invalid expected"):
            require(data[0], data[1], [scenario], invalid)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "cross_source", "negative", "unknown"])
def test_precommit_rejects_incomplete_or_tampered_cost_population(mutation):
    data = _fixture()
    scenario = _scenario(data)
    rows = scenario["adjustments"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[1] = copy.deepcopy(rows[0])
    elif mutation == "cross_source":
        rows[0]["source_sha256"] = "e" * 64
    elif mutation == "negative":
        rows[0]["spread_extra_cash"] = "-0.0001"
    else:
        rows[0]["future_cost"] = "0.0000"
    with pytest.raises(ValueError):
        prepare(data[0], data[1], [scenario])


def test_precommit_rejects_changed_candidate_manifest_and_census():
    data = _fixture()
    scenario = _scenario(data)
    other = copy.deepcopy(data)
    other[0]["candidate_config_sha256"] = "e" * 64
    assert prepare(data[0], data[1], [scenario]) != prepare(other[0], other[1], [scenario])
    changed = copy.deepcopy(data)
    changed[1][0]["row_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="population differs"):
        prepare(changed[0], changed[1], [scenario])


def test_precommit_rejects_duplicate_scenario_ids():
    data = _fixture()
    with pytest.raises(ValueError, match="duplicate"):
        prepare(data[0], data[1], [_scenario(data), _scenario(data)])
