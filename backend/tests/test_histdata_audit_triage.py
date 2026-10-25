"""Offline synthetic consistency and quarantine tests. No market/vendor requests."""
from copy import deepcopy
import json

import pytest

from app.histdata_audit_triage import main, triage_histdata_audit


def fixture_report():
    a = {
        "file": "HISTDATA_COM_ASCII_XAUUSD_M1202610.zip",
        "archive_sha256": "a" * 64, "archive_bytes": 500,
        "price_side": "bid", "format": "ASCII", "instrument": "XAUUSD",
        "source_authenticity_verified": False, "reuse_rights_verified": False,
        "live": False, "executable_bid_ask_verified": False, "can_trade": False,
        "rows": 3, "unique_timestamps": 3, "duplicate_timestamps": 0,
        "conflicting_duplicate_ohlc": 0, "backward_timestamp_jumps": 0,
        "invalid_rows": 0, "outside_filename_period_rows": 0, "zero_volume_rows": 3,
        "observed_gap_events": 0, "unobserved_minutes_between_rows": 0,
        "largest_gap_minutes": 0, "fixed_utc_offset_minutes": -300,
        "first_local_EST": "2026-10-01T00:00:00", "last_local_EST": "2026-10-01T00:02:00",
        "first_utc": "2026-10-01T05:00:00+00:00", "last_utc": "2026-10-01T05:02:00+00:00",
        "status": "FORMAT_OK_NO_COLLISIONS",
    }
    return {"archives": [a], "summary": {"archives": 1, "rows": 3,
            "duplicate_timestamps": 0, "conflicting_duplicate_ohlc": 0,
            "backward_timestamp_jumps": 0, "format_ok_no_collisions": 1,
            "quarantine_review": 0}}


def test_clean_format_never_becomes_backtest_ready():
    report = fixture_report()
    original = deepcopy(report)
    out = triage_histdata_audit(report)
    assert out["summary"]["format_ok_no_collisions"] == 1
    assert out["archives"][0]["triage"] == "FORMAT_ONLY_RIGHTS_UNVERIFIED"
    assert not out["research_ready"] and not out["can_auto_import"]
    assert not out["may_execute_order"] and not out["live"]
    assert report == original


def test_conflicting_duplicates_require_quarantine():
    report = fixture_report()
    row = report["archives"][0]
    row.update(unique_timestamps=2, duplicate_timestamps=1,
               conflicting_duplicate_ohlc=1, backward_timestamp_jumps=1,
               observed_gap_events=1, unobserved_minutes_between_rows=1,
               largest_gap_minutes=2, status="QUARANTINE_REVIEW")
    report["summary"].update(duplicate_timestamps=1, conflicting_duplicate_ohlc=1,
                             backward_timestamp_jumps=1, format_ok_no_collisions=0,
                             quarantine_review=1)
    result = triage_histdata_audit(report)
    assert result["archives"][0]["reasons"] == [
        "DUPLICATE_TIMESTAMPS", "CONFLICTING_DUPLICATE_PRICES", "BACKWARD_TIMESTAMP_JUMPS"]
    assert result["summary"]["quarantine_review"] == 1


@pytest.mark.parametrize("edit", [
    lambda r: r["summary"].update(rows=2),
    lambda r: r["summary"].update(archives=2),
    lambda r: r["archives"][0].update(unique_timestamps=2),
    lambda r: r["archives"][0].update(conflicting_duplicate_ohlc=1),
    lambda r: r["archives"][0].update(source_authenticity_verified=True),
    lambda r: r["archives"][0].update(reuse_rights_verified=True),
    lambda r: r["archives"][0].update(can_trade=True),
    lambda r: r["archives"][0].update(live=True),
    lambda r: r["archives"][0].update(fixed_utc_offset_minutes=-240),
    lambda r: r["archives"][0].update(first_utc="2026-10-01T04:00:00+00:00"),
    lambda r: r["archives"][0].update(last_utc="2026-10-01T04:00:00+00:00"),
    lambda r: r["archives"][0].update(file="../unsafe.zip"),
    lambda r: r["archives"][0].update(rows=True),
    lambda r: r["archives"][0].update(status="QUARANTINE_REVIEW"),
    lambda r: r["archives"][0].update(archive_sha256="invalid"),
    lambda r: r["archives"].append(deepcopy(r["archives"][0])),
])
def test_malformed_or_unverified_claims_fail_closed(edit):
    report = fixture_report()
    edit(report)
    with pytest.raises(ValueError):
        triage_histdata_audit(report)


def test_cli_rejects_duplicate_json_keys_and_symlink(tmp_path, capsys):
    path = tmp_path / "audit.json"
    report = fixture_report()
    path.write_text(json.dumps(report).replace('"rows": 3', '"rows": 1, "rows": 3', 1))
    assert main([str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["result"] == "REJECTED"
    path.write_text(json.dumps(report))
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    assert main([str(link)]) == 2
    assert json.loads(capsys.readouterr().out)["may_execute_order"] is False


def test_cli_success_is_read_only(tmp_path, capsys):
    path = tmp_path / "audit.json"
    raw = json.dumps(fixture_report())
    path.write_text(raw)
    assert main([str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["archives"] == 1
    assert path.read_text() == raw


def test_observed_gap_arithmetic_accepts_only_consistent_minute_span():
    report = fixture_report()
    row = report["archives"][0]
    row.update(last_local_EST="2026-10-01T00:03:00",
               last_utc="2026-10-01T05:03:00+00:00",
               observed_gap_events=1,
               unobserved_minutes_between_rows=1,
               largest_gap_minutes=2)
    result = triage_histdata_audit(report)
    assert result["archives"][0]["triage"] == "FORMAT_ONLY_RIGHTS_UNVERIFIED"
    assert not result["can_auto_import"]


@pytest.mark.parametrize("edit", [
    lambda a: a.update(unobserved_minutes_between_rows=1),
    lambda a: a.update(largest_gap_minutes=2),
    lambda a: a.update(observed_gap_events=1),
    lambda a: a.update(first_local_EST="2026-10-01T00:00:30",
                       first_utc="2026-10-01T05:00:30+00:00"),
    lambda a: a.update(last_local_EST="2026-10-01T00:02:00",
                       last_utc="2026-10-01T05:02:00.500000+00:00"),
])
def test_impossible_observed_gap_metadata_fails_closed(edit):
    report = fixture_report()
    edit(report["archives"][0])
    with pytest.raises(ValueError):
        triage_histdata_audit(report)


@pytest.mark.parametrize("events,missing,largest", [
    (0, 1, 0),
    (2, 1, 2),
    (1, 1, 1),
    (1, 1, 3),
])
def test_gap_event_count_and_largest_gap_reconcile(events, missing, largest):
    report = fixture_report()
    row = report["archives"][0]
    row.update(last_local_EST="2026-10-01T00:03:00",
               last_utc="2026-10-01T05:03:00+00:00",
               observed_gap_events=events,
               unobserved_minutes_between_rows=missing,
               largest_gap_minutes=largest)
    with pytest.raises(ValueError):
        triage_histdata_audit(report)
