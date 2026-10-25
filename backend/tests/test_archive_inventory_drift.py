"""Synthetic offline scanner claims only; no ZIP, network or production data."""
from copy import deepcopy
import json

import pytest

from app.archive_inventory_drift import compare_archive_inventories, main
from test_histdata_audit_triage import fixture_report


def test_identical_inventory_remains_unverified_and_immutable():
    previous = fixture_report()
    original = deepcopy(previous)
    result = compare_archive_inventories(previous, deepcopy(previous))
    assert result["outcome"] == "NO_REPORTED_DIFFERENCES"
    assert result["summary"]["unchanged_shared_filenames"] == 1
    assert result["raw_zip_bytes_verified"] is False
    assert result["research_ready"] is False and result["can_auto_import"] is False
    assert result["live"] is False and result["may_execute_order"] is False
    assert previous == original
    assert "a" * 64 not in json.dumps(result)


def test_changed_bytes_without_claimed_price_change_still_requires_review():
    old = fixture_report()
    new = deepcopy(old)
    new["archives"][0]["archive_sha256"] = "b" * 64
    result = compare_archive_inventories(old, new)
    assert result["outcome"] == "REVIEW_IDENTITY_OR_METADATA_CHANGE"
    assert result["summary"]["same_filename_changed_zip_digest"] == 1
    assert result["summary"]["same_filename_changed_claims"] == 0
    assert result["changed_zip_filename_samples"] == [old["archives"][0]["file"]]


def test_same_zip_digest_with_changed_canonical_claim_is_flagged():
    old = fixture_report()
    new = deepcopy(old)
    new["archives"][0]["canonical_bid_ohlc_sha256"] = "c" * 64
    result = compare_archive_inventories(old, new)
    assert result["summary"]["same_zip_digest_changed_claims"] == 1
    assert result["changed_claim_samples"][0]["changed_fields"] == ["canonical_bid_ohlc_sha256"]
    assert result["changed_claim_samples"][0]["same_reported_zip_digest"] is True
    assert "c" * 64 not in json.dumps(result)


def test_removed_added_same_digest_is_alias_candidate_not_independent_source():
    old = fixture_report()
    new = deepcopy(old)
    new["archives"][0]["file"] = "renamed-histdata.zip"
    result = compare_archive_inventories(old, new)
    assert result["outcome"] == "INVENTORY_MEMBERSHIP_CHANGED"
    assert result["summary"]["added_filenames"] == 1
    assert result["summary"]["removed_filenames"] == 1
    assert result["summary"]["removed_added_same_digest_alias_candidates"] == 1
    assert result["possible_rename_samples"][0]["independent_source_verified"] is False


@pytest.mark.parametrize("limit", [True, -1, 51, 1.5, "20"])
def test_invalid_sample_limit_rejected(limit):
    report = fixture_report()
    with pytest.raises(ValueError):
        compare_archive_inventories(report, report, sample_limit=limit)


def test_zero_sample_limit_preserves_counts():
    old = fixture_report()
    new = deepcopy(old)
    new["archives"][0]["archive_sha256"] = "b" * 64
    out = compare_archive_inventories(old, new, sample_limit=0)
    assert out["summary"]["same_filename_changed_zip_digest"] == 1
    assert out["changed_zip_filename_samples"] == []


def test_invalid_current_inventory_rejected_before_comparison():
    old = fixture_report()
    new = deepcopy(old)
    new["summary"]["rows"] = 100
    with pytest.raises(ValueError):
        compare_archive_inventories(old, new)


def test_cli_read_only_and_duplicate_key_rejection(tmp_path, capsys):
    old = fixture_report()
    p, c = tmp_path / "previous.json", tmp_path / "current.json"
    raw = json.dumps(old)
    p.write_text(raw)
    c.write_text(raw)
    assert main(["--previous", str(p), "--current", str(c)]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "NO_REPORTED_DIFFERENCES"
    assert p.read_text() == raw and c.read_text() == raw
    c.write_text(raw.replace('"rows": 3', '"rows": 1, "rows": 3', 1))
    assert main(["--previous", str(p), "--current", str(c)]) == 2
    assert json.loads(capsys.readouterr().out)["result"] == "REJECTED"
    c.unlink()
    c.symlink_to(p)
    assert main(["--previous", str(p), "--current", str(c)]) == 2
    assert json.loads(capsys.readouterr().out)["may_execute_order"] is False
