"""Offline declared-aggregate JSON exponent-overflow quarantine regressions.

Synthetic malformed JSON only; no market data, secrets, orders or network.
"""
import json
from pathlib import Path

import pytest

from app.offline_sweep_aggregate_audit import (
    audit_aggregate,
    load_declared_aggregate,
    main as aggregate_main,
)
from app.offline_sweep_aggregate_censor_tipping import main as tipping_main
from app.offline_sweep_aggregate_cost_crossing import main as crossing_main

FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")
MAINS = (aggregate_main, tipping_main, crossing_main)


@pytest.mark.parametrize("main", MAINS)
@pytest.mark.parametrize("location", ("top", "nested", "array"))
@pytest.mark.parametrize("numeric", ("1e400", "-1e400"))
def test_exponent_overflow_is_rejected_before_cli_output(
        main, location, numeric, tmp_path, capsys):
    original = FIXTURE.read_text(encoding="utf-8")
    if location == "top":
        raw = original.replace(
            '"protocol":', f'"untrusted_float": {numeric}, "protocol":', 1)
    elif location == "nested":
        raw = original.replace(
            '"state":', f'"untrusted_float": {numeric}, "state":', 1)
    else:
        raw = original.replace(
            '"states": [', f'"untrusted_array": [{{"nested": {numeric}}}], "states": [', 1)
    path = tmp_path / "overflow.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="Nonfinite aggregate JSON numeric exponent"):
        main([str(path)])
    assert capsys.readouterr().out == ""


def test_loader_itself_rejects_overflow_without_needing_audit(tmp_path):
    path = tmp_path / "unused-field.json"
    path.write_text('{"unknown": 1e400}', encoding="utf-8")
    with pytest.raises(ValueError, match="Nonfinite aggregate JSON numeric exponent"):
        load_declared_aggregate(path)


def test_finite_exponent_parses_but_closed_schema_still_rejects(tmp_path):
    raw = FIXTURE.read_text(encoding="utf-8").replace(
        '"protocol":', '"untrusted_float": 1e2, "protocol":', 1)
    path = tmp_path / "finite.json"
    path.write_text(raw, encoding="utf-8")
    parsed = load_declared_aggregate(path)
    assert parsed["untrusted_float"] == 100.0
    with pytest.raises(ValueError, match="unexpected or missing aggregate report fields"):
        audit_aggregate(parsed)


def test_original_report_remains_valid_and_non_executable():
    result = audit_aggregate(load_declared_aggregate(FIXTURE))
    assert result["audit"] == "PASS_DECLARED_AGGREGATE_ARITHMETIC_ONLY"
    assert result["may_execute_order"] is False
    assert result["verified_profitability"] is False
