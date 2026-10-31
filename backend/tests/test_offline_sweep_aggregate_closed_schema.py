"""Frozen-schema tests for declared, non-executable confluence aggregates.

Synthetic mutations of the committed rounded report only; no archives,
network access, trading permissions, or broker execution.
"""
import json
from pathlib import Path

import pytest

from app.offline_sweep_aggregate_audit import (
    audit_aggregate,
    main as aggregate_main,
)
from app.offline_sweep_aggregate_censor_tipping import main as tipping_main
from app.offline_sweep_aggregate_cost_crossing import main as crossing_main

FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")
MAINS = (aggregate_main, tipping_main, crossing_main)
LOCATIONS = ("report", "state", "totals")


def _target(report, location):
    return (report if location == "report" else
            report["states"][0] if location == "state" else report["totals"])


@pytest.mark.parametrize("main", MAINS)
@pytest.mark.parametrize("location", LOCATIONS)
def test_undeclared_fields_fail_closed_before_cli_output(main, location, tmp_path, capsys):
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _target(report, location)["broker_verified_or_selected"] = True
    path = tmp_path / "unexpected.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected or missing aggregate report fields"):
        main([str(path)])
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("main", MAINS)
@pytest.mark.parametrize("location", LOCATIONS)
def test_missing_required_fields_fail_closed_before_cli_output(main, location, tmp_path, capsys):
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = ("may_execute_order" if location == "report" else
                "state" if location == "state" else "observed")
    del _target(report, location)[required]
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected or missing aggregate report fields"):
        main([str(path)])
    assert capsys.readouterr().out == ""


def test_original_fixed_report_remains_audit_only():
    result = audit_aggregate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert result["audit"] == "PASS_DECLARED_AGGREGATE_ARITHMETIC_ONLY"
    assert result["may_execute_order"] is False
    assert result["verified_profitability"] is False
    assert result["source_authenticated"] is False
