"""Synthetic metadata only: no vendor, ZIP, production or broker access."""
from copy import deepcopy
import json

import pytest

from app.archive_inventory_lineage import summarize_archive_lineage


def fixture():
    def entry(name, start, end, digest=None, instrument="XAUUSD"):
        return {"file": name, "instrument": instrument,
                "first_utc": start, "last_utc": end,
                "canonical_bid_ohlc_sha256": digest}
    a = entry("gold-ascii.zip", "2026-10-01T05:00:00+00:00",
              "2026-10-02T05:00:00+00:00", "a" * 64)
    b = entry("gold-mt.zip", "2026-10-01T05:00:00+00:00",
              "2026-10-02T05:00:00+00:00", "a" * 64)
    c = entry("gold-next.zip", "2026-10-02T05:01:00+00:00",
              "2026-10-03T05:00:00+00:00")
    return {"archives": [a, b, c]}


def test_identical_claims_are_not_independent_confirmation():
    report = fixture()
    before = deepcopy(report)
    out = summarize_archive_lineage(report)
    assert out["summary"] == {
        "archives": 3, "canonical_digest_reported": 2,
        "canonical_digest_missing": 1, "claimed_same_digest_pairs": 1,
        "claimed_digest_scope_conflicts": 0,
        "same_instrument_endpoint_range_overlap_pairs": 1,
    }
    assert out["claimed_same_digest_samples"][0]["independent_source_confirmation"] is False
    assert out["possible_range_overlap_samples"][0]["shared_observed_minute_verified"] is False
    assert not out["research_ready"] and not out["can_auto_import"]
    assert not out["live"] and not out["may_execute_order"]
    assert report == before
    assert "a" * 64 not in json.dumps(out)  # Never expose original hashes.


def test_overlapping_endpoint_ranges_do_not_prove_shared_minutes():
    report = fixture()
    report["archives"][2]["first_utc"] = "2026-10-02T04:59:00+00:00"
    out = summarize_archive_lineage(report)
    assert out["summary"]["same_instrument_endpoint_range_overlap_pairs"] == 3
    assert all(not item["shared_observed_minute_verified"]
               for item in out["possible_range_overlap_samples"])


def test_cross_instrument_reused_digest_is_flagged_not_approved():
    report = fixture()
    report["archives"][1]["instrument"] = "WTIUSD"
    out = summarize_archive_lineage(report)
    assert out["summary"]["claimed_digest_scope_conflicts"] == 1
    assert out["summary"]["same_instrument_endpoint_range_overlap_pairs"] == 0
    assert not out["research_ready"]


def test_sample_cap_and_boolean_not_int():
    report = fixture()
    assert not summarize_archive_lineage(report, sample_limit=0)["claimed_same_digest_samples"]
    for bad in (True, -1, 51, 2.5):
        with pytest.raises(ValueError):
            summarize_archive_lineage(report, sample_limit=bad)


@pytest.mark.parametrize("mutate", [
    lambda r: r["archives"][0].update(canonical_bid_ohlc_sha256=""),
    lambda r: r["archives"][0].update(canonical_bid_ohlc_sha256="A" * 64),
    lambda r: r["archives"][0].update(first_utc="2026-10-01T05:00:30+00:00"),
    lambda r: r["archives"][0].update(first_utc="2026-10-01T05:00:00"),
    lambda r: r["archives"][0].update(first_utc="2026-10-04T05:00:00+00:00"),
    lambda r: r["archives"][0].update(file="../evil.zip"),
    lambda r: r["archives"][0].update(instrument="XAU/USD"),
    lambda r: r["archives"].append(deepcopy(r["archives"][0])),
])
def test_bad_metadata_fails_closed(mutate):
    report = fixture()
    mutate(report)
    with pytest.raises(ValueError):
        summarize_archive_lineage(report)


def test_cli_runs_existing_strict_triage_before_lineage(tmp_path, capsys):
    # Reuse the complete, valid scanner-metadata fixture from Loop 1.
    from test_histdata_audit_triage import fixture_report
    from app.archive_inventory_lineage import main

    path = tmp_path / "audit.json"
    report = fixture_report()
    path.write_text(json.dumps(report))
    assert main([str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["canonical_digest_missing"] == 1
    assert out["result"] == "UNTRUSTED_ARCHIVE_LINEAGE_OBSERVATIONS"

    # A malformed scanner summary must be rejected before lineage reporting.
    report["summary"]["rows"] = 999
    path.write_text(json.dumps(report))
    assert main([str(path)]) == 2
    denied = json.loads(capsys.readouterr().out)
    assert denied["result"] == "REJECTED"
    assert denied["can_auto_import"] is False
