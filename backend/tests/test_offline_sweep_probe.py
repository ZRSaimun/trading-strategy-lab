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


def test_censored_entry_reserves_full_horizon_no_overlapping_hypotheses():
    # A long remains unresolved when a continuity segment ends. A later short
    # also qualifies before the gap, but must NOT be admitted while that
    # censored long's holding horizon is still reserved.
    rows = synthetic_bars()
    replacements = {
        30: (100, 101, 80, 100),  # long sweep; stop 80, target 149
        31: (100, 103, 99, 102),  # long confirmation
        32: (103, 104, 99, 103),  # long hypothetical entry
        33: (103, 106, 101, 103), # short sweep; high above prior 104
        34: (101, 102, 99, 100),  # short confirmation
        35: (100, 101, 99, 100),  # short hypothetical entry if not blocked
    }
    for i, (o, h, l, c) in replacements.items():
        b = rows[i]
        rows[i] = Bar(b.time, D(o), D(h), D(l), D(c), 0)
    rows[37:] = [Bar(b.time, b.o, b.h, b.l, b.c, 1) for b in rows[37:]]
    result = research(rows)
    development = result["cohorts"]["development"]
    assert development["censored_due_to_gaps_or_boundaries"] == 1
    assert development["cost_scenarios"][0]["count"] == 0
    assert result["may_execute_order"] is False


@pytest.mark.parametrize(
    "direction,signal,confirm,entry,adverse_bar",
    [
        ("long", (100, 101, 98, 100), (100, 103, 99, 102),
         (103, 110, 99, 103), (80, 114, 79, 100)),
        ("short", (100, 102, 99, 100), (100, 100, 97, 98),
         (97, 100, 90, 95), (120, 121, 86, 100)),
    ],
)
def test_adverse_source_open_gap_does_not_credit_exact_stop(
    direction, signal, confirm, entry, adverse_bar
):
    # Long: entry 103, stop 98, gap open 80 -> -23/5 = -4.6 R.
    # Short: entry 97, stop 102, gap open 120 -> -23/5 = -4.6 R.
    # Both gap bars ALSO touch the 2R target; stop-first still wins.
    rows = synthetic_bars()
    for index, values in zip((30, 31, 32, 33),
                             (signal, confirm, entry, adverse_bar)):
        b = rows[index]
        rows[index] = Bar(b.time, *(D(v) for v in values), b.segment)
    result = research(rows)
    assert result["protocol"] == "source-local-sweep-confirmation-v2"
    cases = result["cohorts"]["development"]["cost_scenarios"]
    assert cases[0]["count"] == 1, direction
    assert D(cases[0]["mean_net_r"]) == D("-4.6"), direction
    assert D(cases[1]["mean_net_r"]) < D("-4.6")
    assert result["may_execute_order"] is False
