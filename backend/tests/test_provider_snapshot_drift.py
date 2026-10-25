"""Synthetic read-only drift checks; never contact a provider or production DB."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest

from app.completed_candle_quality import assess_completed_m1
from app.provider_snapshot_drift import compare_staging_snapshots, main
from test_provider_staging_reconciliation import fixture_data


def version(previous, *, times=None, change_close=False, received=420):
    old_manifest, _, old_rows = previous
    rows = deepcopy(old_rows)
    if times is not None:
        rows = [deepcopy(rows[0]) for _ in times]
        for row, t in zip(rows, times):
            row["time"] = t
    if change_close:
        rows[0]["close"] = 100.5
    for row in rows:
        row["retrieved_at"] = received - 60
    values = []
    for row in rows:
        source = {"time": datetime.fromtimestamp(row["time"], timezone.utc).isoformat()}
        source.update({k: str(row[k]) for k in ("open", "high", "low", "close")})
        values.append(source)
    archive = json.dumps({"meta": {"symbol": "XAU/USD", "interval": "1min",
                                    "exchange_timezone": "UTC"}, "values": values},
                         separators=(",", ":")).encode()
    manifest = deepcopy(old_manifest)
    manifest.update(retrieved_at=received - 60, request_started_at=received - 60,
                    response_received_at=received, request_end=rows[-1]["time"],
                    request_limit=len(rows), rows=len(rows), start=rows[0]["time"],
                    end=rows[-1]["time"], sha256=hashlib.sha256(archive).hexdigest(),
                    quality=assess_completed_m1(rows, received))
    manifest["gaps"] = manifest["quality"]["observed_timestamp_gaps"]
    return manifest, archive, rows


def test_identical_observed_values_are_not_vendor_authentication():
    prior = fixture_data()
    current = version(prior)
    unchanged = deepcopy((prior, current))
    report = compare_staging_snapshots(*prior, *current)
    assert report["outcome"] == "SAME_OBSERVED_VALUES_AND_COVERAGE"
    assert report["shared_observed_minutes"] == 2
    assert report["unchanged_shared_minutes"] == 2
    assert report["revised_shared_minutes"] == 0
    assert report["may_replace_dataset"] is False
    assert report["may_execute_order"] is False and report["live"] is False
    assert (prior, current) == unchanged


def test_revision_and_coverage_are_reported_without_prices():
    prior = fixture_data()
    current = version(prior, times=[60, 240], change_close=True)
    report = compare_staging_snapshots(*prior, *current)
    assert report["outcome"] == "OBSERVED_VALUE_OR_COVERAGE_DRIFT"
    assert (report["shared_observed_minutes"], report["revised_shared_minutes"],
            report["removed_observed_minutes"], report["added_observed_minutes"]) == (1, 1, 1, 1)
    assert report["revised_utc_samples"] == ["1970-01-01T00:01:00+00:00"]
    assert report["removed_utc_samples"] == ["1970-01-01T00:03:00+00:00"]
    assert report["added_utc_samples"] == ["1970-01-01T00:04:00+00:00"]
    assert "100.5" not in json.dumps(report)


def test_shifted_window_edges_are_not_mislabelled_as_shared_coverage_gaps():
    prior = fixture_data()  # observed at 60 and 180
    current = version(prior, times=[60, 240], received=480)
    report = compare_staging_snapshots(*prior, *current)
    assert report["observed_range_overlap"] is True
    assert report["observed_overlap_start_utc"] == "1970-01-01T00:01:00+00:00"
    assert report["observed_overlap_end_utc"] == "1970-01-01T00:03:00+00:00"
    assert report["removed_within_observed_overlap"] == 1
    assert report["added_within_observed_overlap"] == 0
    assert report["removed_outside_observed_overlap"] == 0
    assert report["added_outside_observed_overlap"] == 1
    assert report["overlap_coverage_differs"] is True


def test_identical_observed_windows_have_no_coverage_difference():
    prior = fixture_data()
    report = compare_staging_snapshots(*prior, *version(prior))
    assert report["observed_range_overlap"] is True
    assert report["added_within_observed_overlap"] == 0
    assert report["removed_within_observed_overlap"] == 0
    assert report["added_outside_observed_overlap"] == 0
    assert report["removed_outside_observed_overlap"] == 0
    assert report["overlap_coverage_differs"] is False


def test_no_overlap_does_not_claim_identical():
    prior = fixture_data()
    current = version(prior, times=[300, 360], received=480)
    report = compare_staging_snapshots(*prior, *current)
    assert report["outcome"] == "NO_SHARED_OBSERVED_MINUTES"
    assert report["shared_observed_minutes"] == 0
    assert report["observed_range_overlap"] is False
    assert report["observed_overlap_start_utc"] is None
    assert report["observed_overlap_end_utc"] is None
    assert report["removed_outside_observed_overlap"] == 2
    assert report["added_outside_observed_overlap"] == 2
    assert report["overlap_coverage_differs"] is False


def test_revised_timestamp_samples_can_be_suppressed():
    prior = fixture_data()
    current = version(prior, change_close=True)
    report = compare_staging_snapshots(*prior, *current, sample_limit=0)
    assert report["revised_shared_minutes"] == 1
    assert report["revised_utc_samples"] == []


@pytest.mark.parametrize("bad_limit", [-1, 21, True, 1.0, "5"])
def test_invalid_sample_limits_fail_closed(bad_limit):
    prior = fixture_data()
    with pytest.raises(ValueError, match="sample_limit"):
        compare_staging_snapshots(*prior, *prior, sample_limit=bad_limit)


def test_invalid_archive_fails_before_comparison():
    prior = fixture_data()
    current = version(prior)
    current = (current[0], current[1] + b" ", current[2])
    with pytest.raises(ValueError, match="SHA-256"):
        compare_staging_snapshots(*prior, *current)


def test_reverse_receipt_chronology_is_rejected():
    prior = version(fixture_data(), received=420)
    older = fixture_data()
    with pytest.raises(ValueError, match="predates"):
        compare_staging_snapshots(*prior, *older)


def write_cli_inputs(tmp_path, previous, current):
    args = []
    for label, dataset in (("previous", previous), ("current", current)):
        for name, value in zip(("manifest", "archive", "candles"), dataset):
            path = tmp_path / (label + "-" + name + ".json")
            path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
            args.extend(("--" + label + "-" + name, str(path)))
    return args


def test_cli_is_read_only_and_emits_no_prices(tmp_path, capsys):
    prior = fixture_data()
    args = write_cli_inputs(tmp_path, prior, version(prior, change_close=True))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["revised_shared_minutes"] == 1
    assert "100.5" not in json.dumps(report)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_cli_rejects_symlink_and_ambiguous_manifest(tmp_path, capsys):
    prior = fixture_data()
    args = write_cli_inputs(tmp_path, prior, version(prior))
    manifest = tmp_path / "current-manifest.json"
    raw = manifest.read_text()
    manifest.write_text(raw.replace('"provider":', '"provider":"spoofed","provider":', 1))
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["result"] == "REJECTED"
    manifest.write_text(raw)
    archive = tmp_path / "current-archive.json"
    link = tmp_path / "link.json"
    link.symlink_to(archive)
    args[args.index(str(archive))] = str(link)
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["may_replace_dataset"] is False
