"""Synthetic, offline-only research regressions; no trading approval."""
from datetime import datetime, timedelta
import hashlib
import zipfile

import pytest

from app.offline_m1_cost_sensitivity import (
    audit_m1_cost_sensitivity, audit_histdata_ascii_zip,
)


def fixture_bars(count=45):
    start = datetime(2025, 1, 2, 10, 0)
    rows = []
    for i in range(count):
        when = (start + timedelta(minutes=i)).strftime("%Y%m%d %H%M%S")
        rows.append([when, "100", "101", "99", "100", "0"])
    rows[20][1:5] = ["100", "101", "98", "100"]  # 20-bar low sweep and reclaim
    rows[21][1:5] = ["102", "104", "102", "103"]  # MSS + wick FVG
    rows[22][1:5] = ["103", "104", "102", "103"]  # next-open entry
    rows[36][1:5] = ["103", "105", "102", "104"]  # 15th bar exit
    return rows


def audit(rows, **kwargs):
    return audit_m1_cost_sensitivity(
        rows, instrument="XAUUSD", provider="HistData",
        archive_sha256="a" * 64, **kwargs,
    )


def test_next_open_fixed_horizon_costs_and_nonexecution():
    report = audit(fixture_bars())
    assert report["confirmed_count"] == 1
    assert report["all_exploratory"]["count"] == 1
    # Signal closes at minute 21; fill is minute 22 open 103, not signal close.
    # The fixed 15th candle closes at minute 36 at 104.
    assert report["all_exploratory"]["mean_gross_bps"] == pytest.approx(
        (104 - 103) / 103 * 10000, abs=0.000001
    )
    assert report["all_exploratory"]["mean_net_bps_by_roundtrip_cost"]["10"] == pytest.approx(
        report["all_exploratory"]["mean_gross_bps"] - 10, abs=0.000002
    )
    assert not report["trade_authorized"] and not report["verified_profitability"]
    assert not report["protected_holdout"] and not report["executable_quotes_verified"]


def test_after_exit_changes_digest_but_not_fixed_horizon_outcome():
    first = fixture_bars()
    changed = fixture_bars()
    changed[-1][1:5] = ["150", "151", "149", "150"]
    a, b = audit(first), audit(changed)
    assert a["bar_manifest_sha256"] != b["bar_manifest_sha256"]
    assert a["all_exploratory"] == b["all_exploratory"]


def test_gap_censors_fixed_horizon_instead_of_filling_across_gap():
    rows = fixture_bars(38)
    clean = audit(rows)
    broken = audit(rows[:28] + rows[29:])
    assert clean["all_exploratory"]["count"] >= 1
    assert broken["censored_gap_or_end"] >= 1
    assert broken["all_exploratory"]["count"] < clean["all_exploratory"]["count"]


def test_source_wall_backward_and_duplicate_are_counted_not_sorted():
    rows = fixture_bars()
    rows.insert(4, list(rows[3]))
    result = audit(rows)
    assert result["adjacent_duplicates"] == 1
    assert result["timestamp_discontinuities"] >= 1


@pytest.mark.parametrize("kwargs", [
    {"roundtrip_cost_bps": (10, 5)},
    {"roundtrip_cost_bps": (0, 0)},
    {"roundtrip_cost_bps": (True,)},
    {"horizon_minutes": True},
    {"archive_sha256": "invalid"},
    {"instrument": "../bad"},
])
def test_reject_invalid_policy_and_source(kwargs):
    defaults = {"instrument": "XAUUSD", "provider": "HistData", "archive_sha256": "a" * 64}
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        audit_m1_cost_sensitivity(fixture_bars(), **defaults)


def test_reject_malformed_ohlc():
    rows = fixture_bars()
    rows[2][2] = "98"
    with pytest.raises(ValueError):
        audit(rows)


def test_deterministic_fingerprint():
    assert audit(fixture_bars()) == audit(fixture_bars())


def test_readonly_zip_parser_matches_direct_audit(tmp_path):
    path = tmp_path / "test.zip"
    rows = fixture_bars()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("source.csv", "\n".join(";".join(x) for x in rows) + "\n")
    report = audit_histdata_ascii_zip(path, instrument="XAUUSD")
    expected = audit_m1_cost_sensitivity(
        rows, instrument="XAUUSD", provider="HistData",
        archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert report == expected


def test_zip_rejects_multiple_csv_members(tmp_path):
    path = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.csv", "")
        archive.writestr("two.csv", "")
    with pytest.raises(ValueError, match="Exactly one"):
        audit_histdata_ascii_zip(path, instrument="XAUUSD")


def test_rejects_nonminute_wall_time():
    rows = fixture_bars()
    rows[1][0] = "20250102 100101"
    with pytest.raises(ValueError):
        audit(rows)
