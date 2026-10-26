"""Synthetic tests only; never depend on proprietary archive bytes."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zipfile import ZipFile
import pytest
from app.offline_sweep_probe import Bar, read_archive, research


def synthetic_bars():
    t = datetime(2025, 1, 1)
    rows = [Bar(t + timedelta(minutes=15*i), D(100), D(101), D(99), D(100), 0)
            for i in range(200)]
    rows[30] = Bar(rows[30].time, D(100), D(101), D(98), D(100), 0)
    rows[31] = Bar(rows[31].time, D(100), D(103), D(99), D(102), 0)
    rows[32] = Bar(rows[32].time, D(103), D(114), D(97), D(100), 0)
    return rows


def test_conservative_same_bar_stop_precedes_target():
    result = research(synthetic_bars())
    cases = result["cohorts"]["development"]["cost_scenarios"]
    assert cases[0]["count"] == 1
    assert D(cases[0]["mean_net_r"]) == -1
    assert D(cases[1]["mean_net_r"]) < -1
    assert [c["additional_round_trip_bps"] for c in cases] == [0, 5, 10, 20]
    assert result["cohorts"]["exploratory_later"]["cost_scenarios"][0]["count"] == 0
    assert not result["verified_profitability"] and not result["may_execute_order"]


def test_confirmation_causal_and_no_gap_crossing():
    rows = synthetic_bars()
    rows[31] = Bar(rows[31].time, D(100), D(101), D(99), D(100), 0)
    assert research(rows)["cohorts"]["development"]["cost_scenarios"][0]["count"] == 0
    rows = synthetic_bars()
    rows[31] = Bar(rows[31].time, D(100), D(103), D(99), D(102), 1)
    assert research(rows)["cohorts"]["development"]["cost_scenarios"][0]["count"] == 0


def test_archive_read_only_complete_buckets(tmp_path):
    path = tmp_path / "sample.zip"
    rows = []
    t = datetime(2025, 1, 1)
    for i in list(range(15)) + list(range(20, 23)):
        rows.append((t + timedelta(minutes=i)).strftime("%Y%m%d %H%M%S") +
                    ";100;101;99;100;0\n")
    with ZipFile(path, "w") as z:
        z.writestr("DAT_ASCII_XAUUSD_M1_2025.csv", "".join(rows))
    bars, q = read_archive(path)
    assert len(bars) == 1
    assert q["complete_15m"] == 1 and q["discarded_partial_15m"] == 1
    assert q["discontinuities"] == 1
    assert q["timezone"] == "UNVERIFIED_SOURCE_LOCAL"


def test_archive_rejects_invalid_price_and_nested_csv(tmp_path):
    path = tmp_path / "bad.zip"
    with ZipFile(path, "w") as z:
        z.writestr("DAT_ASCII_XAUUSD_M1_2025.csv",
                   "20250101 000000;100;99;98;100;0\n")
    with pytest.raises(ValueError, match="Invalid M1 row"):
        read_archive(path)
    with ZipFile(path, "w") as z:
        z.writestr("dir/DAT_ASCII_XAUUSD_M1_2025.csv",
                   "20250101 000000;100;101;99;100;0\n")
    with pytest.raises(ValueError, match="flat CSV"):
        read_archive(path)


def test_fail_closed_protocol_inputs():
    with pytest.raises(ValueError):
        research(synthetic_bars(), embargo=1, horizon=16)


def test_invalid_minute_alignment_and_volume(tmp_path):
    path = tmp_path / "bad.zip"
    for row in ("20250101 000001;100;101;99;100;0\n",
                "20250101 000000;100;101;99;100;NaN\n"):
        with ZipFile(path, "w") as z:
            z.writestr("DAT_ASCII_XAUUSD_M1_2025.csv", row)
        with pytest.raises(ValueError, match="Invalid M1 row"):
            read_archive(path)
