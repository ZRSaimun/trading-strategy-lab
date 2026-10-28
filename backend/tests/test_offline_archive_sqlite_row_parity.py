"""Synthetic original-archive / SQLite parity regressions; no vendor data or orders."""
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.offline_archive_sqlite_row_parity import audit_original_ascii_sqlite, main

DATASET = "a" * 64
CSV_MEMBER = "DAT_ASCII_SYNTHETIC_M1.csv"


def make_pair(tmp_path, *, duplicate=True, precision=False, offset=-300):
    tmp_path.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "original.zip"
    db = tmp_path / "research.sqlite"
    open_price = "100.123456789123456789" if precision else "100.0"
    rows = [
        ("20250101 000000", open_price, "101", "99", open_price, "0"),
        ("20250101 000100", "100", "102", "99", "101", "0"),
    ]
    if duplicate:
        rows.append(rows[0])
    rows.append(("20250101 000200", "101", "103", "100", "102", "0"))
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(CSV_MEMBER, "".join(";".join(r) + "\n" for r in rows))
        zf.writestr("status.txt", "synthetic status, not vendor evidence")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    with sqlite3.connect(db) as con:
        con.executescript("""
            CREATE TABLE historical_datasets (
                id TEXT PRIMARY KEY, provider TEXT, format TEXT, state TEXT,
                utc_offset_minutes INTEGER, archive_sha256 TEXT,
                accepted INTEGER, rejected INTEGER);
            CREATE TABLE historical_candles (
                dataset_id TEXT, time INTEGER, open FLOAT, high FLOAT,
                low FLOAT, close FLOAT, source_member TEXT, source_line INTEGER);
        """)
        con.execute("INSERT INTO historical_datasets VALUES (?,?,?,?,?,?,?,?)",
                    (DATASET, "HistData", "ascii", "READY", offset, sha,
                     3, int(duplicate)))
        accepted_lines = [1, 2, 4] if duplicate else [1, 2, 3]
        for line in accepted_lines:
            stamp, o, h, l, c, _ = rows[line - 1]
            naive = datetime.strptime(stamp, "%Y%m%d %H%M%S")
            epoch = int(naive.replace(
                tzinfo=timezone(timedelta(minutes=offset))).timestamp())
            con.execute("INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?,?)",
                        (DATASET, epoch, float(o), float(h), float(l),
                         float(c), CSV_MEMBER, line))
    return archive, db, sha


def test_exact_row_parity_with_rejected_backward_duplicate(tmp_path):
    archive, db, sha = make_pair(tmp_path)
    original_zip, original_db = archive.read_bytes(), db.read_bytes()
    report = audit_original_ascii_sqlite(archive, db, DATASET, sha)
    assert report["source_rows"] == 4
    assert report["source_admitted"] == 3
    assert report["source_quarantined_nonmonotonic"] == 1
    assert report["source_backward_jumps"] == 1
    assert report["zip_identity_verified"] is True
    assert report["exact_original_decimal_storage_verified"] is True
    assert report["source_clock_verified"] is False
    assert report["independent_holdout_verified"] is False
    assert report["may_execute_order"] is False
    assert archive.read_bytes() == original_zip
    assert db.read_bytes() == original_db


def test_no_duplicate_source_and_declared_offset(tmp_path):
    archive, db, sha = make_pair(tmp_path, duplicate=False, offset=330)
    result = audit_original_ascii_sqlite(archive, db, DATASET, sha)
    assert result["source_quarantined_nonmonotonic"] == 0
    assert result["declared_utc_offset_minutes"] == 330


def test_source_decimal_precision_loss_is_disclosed(tmp_path):
    archive, db, sha = make_pair(tmp_path, precision=True)
    result = audit_original_ascii_sqlite(archive, db, DATASET, sha)
    assert result["original_decimal_values_not_preserved_by_float"] == 2
    assert result["exact_original_decimal_storage_verified"] is False


@pytest.mark.parametrize("column, replacement, error", [
    ("open", 999.0, "FLOAT parity"),
    ("open", float("inf"), "FLOAT parity"),
    ("source_line", 888, "lineage"),
    ("source_member", "wrong.csv", "lineage"),
    ("time", 42, "lineage"),
])
def test_rejects_stored_price_or_lineage_changes(tmp_path, column, replacement, error):
    archive, db, sha = make_pair(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute(f"UPDATE historical_candles SET {column}=? WHERE source_line=2",
                    (replacement,))
    with pytest.raises(ValueError, match=error):
        audit_original_ascii_sqlite(archive, db, DATASET, sha)


@pytest.mark.parametrize("column, replacement", [
    ("accepted", 4), ("rejected", 0), ("state", "IMPORTING"),
    ("utc_offset_minutes", 0), ("archive_sha256", "c" * 64),
])
def test_rejects_bad_metadata_or_census(tmp_path, column, replacement):
    archive, db, sha = make_pair(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute(f"UPDATE historical_datasets SET {column}=? WHERE id=?",
                    (replacement, DATASET))
    with pytest.raises(ValueError):
        audit_original_ascii_sqlite(archive, db, DATASET, sha)


def test_rejects_archive_change_and_wrong_identity(tmp_path):
    archive, db, sha = make_pair(tmp_path)
    with pytest.raises(ValueError, match="SHA-256"):
        audit_original_ascii_sqlite(archive, db, DATASET, "c" * 64)
    archive.write_bytes(archive.read_bytes() + b"mutation")
    with pytest.raises(ValueError, match="SHA-256"):
        audit_original_ascii_sqlite(archive, db, DATASET, sha)
    with pytest.raises(ValueError, match="SHA-256"):
        audit_original_ascii_sqlite(archive, db, "not-a-digest", sha)


def test_rejects_extra_sqlite_rows(tmp_path):
    archive, db, sha = make_pair(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?,?)",
            (DATASET, 999999, 100.0, 101.0, 99.0, 100.0, CSV_MEMBER, 99))
    with pytest.raises(ValueError, match="unmatched"):
        audit_original_ascii_sqlite(archive, db, DATASET, sha)


def test_cli_emits_only_aggregate_safe_evidence(tmp_path, capsys):
    archive, db, sha = make_pair(tmp_path)
    main([str(archive), str(db), "--dataset-id", DATASET,
          "--expected-archive-sha256", sha])
    output = json.loads(capsys.readouterr().out)
    assert output["source_admitted"] == 3
    assert output["source_authenticity_verified"] is False
    assert output["verified_profitability"] is False
    assert "100.0" not in json.dumps(output)
