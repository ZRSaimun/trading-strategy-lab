"""Synthetic SQLite adapter regressions; no proprietary archive bytes or broker I/O."""
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.offline_sweep_sqlite_replay import replay_declared_sqlite, main

DATASET = "a" * 64
SOURCE = "b" * 64


def build_db(tmp_path, *, gap=False, corrupt=False, accepted_delta=0):
    path = tmp_path / "research.sqlite"
    tmp_path.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE historical_datasets (
            id TEXT PRIMARY KEY, provider TEXT, instrument TEXT, format TEXT,
            utc_offset_minutes INTEGER, archive_sha256 TEXT, state TEXT,
            accepted INTEGER, rejected INTEGER);
        CREATE TABLE historical_candles (
            dataset_id TEXT, time INTEGER, open FLOAT, high FLOAT,
            low FLOAT, close FLOAT, volume FLOAT, source_member TEXT,
            source_line INTEGER, PRIMARY KEY(dataset_id,time));
    """)
    start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    candles = []
    for bar in range(200):
        o, h, l, c = (100, 101, 99, 100)
        if bar == 30:
            o, h, l, c = 100, 101, 98, 100
        elif bar == 31:
            o, h, l, c = 100, 103, 99, 102
        elif bar == 32:
            o, h, l, c = 103, 114, 97, 100
        for minute in range(15):
            index = bar * 15 + minute
            if gap and index == 10:
                continue
            if corrupt and index == 10:
                h = 1
            candles.append((DATASET, start + index * 60,
                            o, h, l, c, 0, "DAT_ASCII_TEST_M1_2025.csv", index + 1))
    con.executemany(
        "INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?,?,?)", candles)
    con.execute(
        "INSERT INTO historical_datasets VALUES (?,?,?,?,?,?,?,?,?)",
        (DATASET, "HistData", "NSXUSD-CFD", "ascii", -300,
         SOURCE, "READY", len(candles) + accepted_delta, 0))
    con.commit()
    con.close()
    return path


def test_replay_frozen_engine_uses_synthetic_source_local_m1(tmp_path):
    path = build_db(tmp_path)
    before = path.read_bytes()
    result = replay_declared_sqlite(path, DATASET, SOURCE)
    assert result["m1_accepted"] == 3000
    assert result["complete_m15"] == 200
    assert result["partial_m15_discarded"] == 0
    assert result["cohorts"]["development"]["observed"] == 1
    assert D(result["cohorts"]["development"]["cost_scenarios"][0]
             ["observed_mean_net_r"]) == -1
    assert result["cohorts"]["exploratory_later"]["observed"] == 0
    assert not result["source_authenticated"]
    assert not result["verified_profitability"]
    assert not result["may_execute_order"]
    assert path.read_bytes() == before


def test_gap_discarded_not_synthetically_filled(tmp_path):
    result = replay_declared_sqlite(build_db(tmp_path, gap=True), DATASET, SOURCE)
    assert result["m1_accepted"] == 2999
    assert result["complete_m15"] == 199
    assert result["partial_m15_discarded"] == 2  # before and after the gap
    assert result["m1_discontinuities"] == 1


@pytest.mark.parametrize("wrong", [
    {"dataset_id": "not-a-hash"},
    {"expected_archive_sha256": "not-a-hash"},
    {"expected_archive_sha256": "c" * 64},
])
def test_requires_explicit_source_identity(tmp_path, wrong):
    kwargs = {"dataset_id": DATASET, "expected_archive_sha256": SOURCE}
    kwargs.update(wrong)
    with pytest.raises(ValueError):
        replay_declared_sqlite(build_db(tmp_path), **kwargs)


def test_rejects_corrupt_ohlc_and_metadata_count(tmp_path):
    with pytest.raises(ValueError, match="OHLC geometry"):
        replay_declared_sqlite(build_db(tmp_path / "bad", corrupt=True), DATASET, SOURCE)
    with pytest.raises(ValueError, match="row count"):
        replay_declared_sqlite(build_db(tmp_path / "count", accepted_delta=1),
                               DATASET, SOURCE)


def test_cli_is_machine_readable_and_non_executing(tmp_path, capsys):
    path = build_db(tmp_path)
    main([str(path), "--dataset-id", DATASET,
          "--expected-archive-sha256", SOURCE])
    result = json.loads(capsys.readouterr().out)
    assert result["audit"] == "SQLITE_FLOAT_STAGING_FROZEN_DECIMAL_ENGINE_REPLAY"
    assert result["broker_execution_costs_verified"] is False
    assert result["independent_holdout_verified"] is False


def test_replay_pins_metadata_and_candles_to_one_wal_snapshot(tmp_path, monkeypatch):
    """A concurrent READY import cannot splice two SQLite revisions together."""
    path = build_db(tmp_path)
    real_connect = sqlite3.connect
    with real_connect(path) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    changed = []

    class InterceptConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=()):
            if "FROM historical_candles" in sql and not changed:
                # This executes after the adapter has read dataset metadata.
                # In WAL mode the concurrent writer can commit while a reader
                # retains its previous snapshot. Without explicit BEGIN, the
                # following candle SELECT would see the new revision instead.
                with real_connect(path) as writer:
                    writer.execute(
                        "UPDATE historical_datasets SET accepted=accepted+1 WHERE id=?",
                        (DATASET,))
                    writer.execute(
                        "INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?,?,?)",
                        (DATASET,
                         int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
                         + 3000 * 60,
                         100, 101, 99, 100, 0,
                         "DAT_ASCII_TEST_M1_2025.csv", 3001))
                changed.append(True)
            return self.connection.execute(sql, params)

        def close(self):
            self.connection.close()

    monkeypatch.setattr(
        "app.offline_sweep_sqlite_replay.sqlite3.connect",
        lambda *args, **kwargs: InterceptConnection(real_connect(*args, **kwargs)))
    report = replay_declared_sqlite(path, DATASET, SOURCE)
    assert changed == [True]
    assert report["m1_accepted"] == 3000
    assert report["complete_m15"] == 200
    with real_connect(path) as writer:
        assert writer.execute(
            "SELECT accepted FROM historical_datasets WHERE id=?",
            (DATASET,)).fetchone()[0] == 3001
        assert writer.execute(
            "SELECT count(*) FROM historical_candles WHERE dataset_id=?",
            (DATASET,)).fetchone()[0] == 3001
