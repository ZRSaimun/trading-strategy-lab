"""Strict offline aggregate JSON input tests; no private archive or broker data."""
import json
from pathlib import Path

import pytest

from app.offline_sweep_aggregate_audit import (
    MAX_AGGREGATE_JSON_BYTES,
    load_declared_aggregate,
    main as aggregate_main,
)
from app.offline_sweep_aggregate_censor_tipping import main as tipping_main
from app.offline_sweep_aggregate_cost_crossing import main as crossing_main

FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")
CLI_MAINS = (aggregate_main, tipping_main, crossing_main)


@pytest.mark.parametrize("main", CLI_MAINS)
def test_valid_declared_aggregate_cli_still_runs(main, capsys):
    main([str(FIXTURE)])
    result = json.loads(capsys.readouterr().out)
    assert result["may_execute_order"] is False
    assert result["verified_profitability"] is False


@pytest.mark.parametrize("main", CLI_MAINS)
@pytest.mark.parametrize("level", ("top_level", "nested_state"))
def test_duplicate_keys_rejected_before_any_report(main, level, tmp_path, capsys):
    raw = FIXTURE.read_text(encoding="utf-8")
    if level == "top_level":
        raw = raw.replace('"may_execute_order": false,',
                          '"may_execute_order": true, "may_execute_order": false,', 1)
    else:
        raw = raw.replace('"observed": 1243,',
                          '"observed": 9999, "observed": 1243,', 1)
    target = tmp_path / "duplicate.json"
    target.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate aggregate JSON key"):
        main([str(target)])
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("main", CLI_MAINS)
def test_oversized_input_rejected_without_parsing(main, tmp_path, capsys):
    target = tmp_path / "too-large.json"
    target.write_bytes(b" " * (MAX_AGGREGATE_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds bounded input size"):
        main([str(target)])
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("main", CLI_MAINS)
def test_nonstandard_nan_rejected_even_in_unused_field(main, tmp_path, capsys):
    raw = FIXTURE.read_text(encoding="utf-8").replace(
        '"protocol":', '"unknown_extra_field": NaN, "protocol":', 1)
    target = tmp_path / "nonfinite.json"
    target.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="Nonstandard aggregate JSON numeric constant"):
        main([str(target)])
    assert capsys.readouterr().out == ""


def test_loader_does_not_mutate_or_claim_authenticity():
    result = load_declared_aggregate(FIXTURE)
    assert result["source_status"] == "UNAUTHENTICATED"
    assert result["independent_holdout"] is False
    assert result["may_execute_order"] is False
