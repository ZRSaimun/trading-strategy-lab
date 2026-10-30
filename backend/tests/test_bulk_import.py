"""Isolated synthetic HistData archive integration checks (no vendor data)."""
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from sqlalchemy import create_engine, select, func

from app.bulk_import import create_schema, ingest, datasets, candles, issues


def archive(tmp_path, content, name="ascii.zip", member="DAT_ASCII_XAUUSD_M1_202610.csv"):
    dest = tmp_path / name
    with ZipFile(dest, "w", ZIP_DEFLATED) as zf:
        zf.writestr(member, content)
    return dest


def engine(tmp_path):
    e = create_engine("sqlite:///" + str(tmp_path / "research.sqlite"))
    create_schema(e)
    return e


def ascii_rows():
    return ("20261001 090000;1;2;0.5;1.5;0\n"
            "20261001 090100;2;3;1;2.5;0\n"
            "20261001 090200;3;4;2;3.5;0\n"
            "20261001 090200;8;9;7;8.5;0\n"  # duplicate -> quarantine
            "20261001 090300;1;0;2;1.5;0\n"  # invalid OHLC
            "20261001 090400;4;5;3;4.5;0\n")


def test_import_preserves_quotes_timezone_and_quarantine(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, ascii_rows())
    result = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData",
                    rights_confirmed=True, chunk_rows=2)
    assert (result["state"], result["accepted"], result["rejected"]) == ("QUARANTINED", 4, 2)
    with e.connect() as con:
        rows = con.execute(select(candles).order_by(candles.c.time)).mappings().all()
        assert len(rows) == 4
        # Fixed UTC-5: 09:00 EST is 14:00 UTC.
        assert rows[0]["time"] == 1790863200
        assert rows[0]["open"] == 1.0 and rows[0]["volume"] == 0
        assert con.scalar(select(func.count()).select_from(issues)) == 2
    again = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData",
                   rights_confirmed=True)
    assert again["already_complete"] and again["state"] == "QUARANTINED"


def test_resume_after_committed_chunk(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, ascii_rows())
    first = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData",
                   rights_confirmed=True, chunk_rows=2, max_rows_per_run=2)
    assert first["paused"]
    second = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData",
                    rights_confirmed=True, chunk_rows=2)
    assert second["accepted"] == 4
    assert second["rejected"] == 2
    assert second["state"] == "QUARANTINED"
    with e.connect() as con:
        assert con.scalar(select(func.count()).select_from(candles)) == 4


def test_provider_identity_never_overwrites(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, ascii_rows())
    a = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData", rights_confirmed=True)
    b = ingest(e, p, instrument="XAUUSD-CFD", provider="SecondVendor", rights_confirmed=True)
    assert a["dataset_id"] != b["dataset_id"]
    with e.connect() as con:
        assert con.scalar(select(func.count()).select_from(candles)) == 8


def test_permission_guard_and_malformed_rows(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, ascii_rows())
    with pytest.raises(ValueError, match="confirm"):
        ingest(e, p, instrument="XAUUSD-CFD", provider="HistData")
    with pytest.raises(ValueError, match="Invalid instrument"):
        ingest(e, p, instrument="INVALID/INSTRUMENT", provider="HistData", rights_confirmed=True)
    with e.connect() as con:
        assert con.scalar(select(func.count()).select_from(datasets)) == 0


def test_metatrader_m1(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, "2012.02.01,00:00,1.0,2.0,0.5,1.5,0\n",
                "mt.zip", "DAT_MT_EURUSD_M1_201202.csv")
    result = ingest(e, p, instrument="EURUSD-FX", provider="HistData",
                    file_format="mt", rights_confirmed=True)
    assert result["accepted"] == 1


def test_requires_schema_and_rejects_bad_zip(tmp_path):
    e = create_engine("sqlite:///" + str(tmp_path / "no_schema.sqlite"))
    p = archive(tmp_path, ascii_rows())
    with pytest.raises(Exception):
        ingest(e, p, instrument="XAUUSD-CFD", provider="HistData", rights_confirmed=True)
    e = engine(tmp_path)
    p.write_bytes(b"not a zip")
    with pytest.raises(Exception):
        ingest(e, p, instrument="XAUUSD-CFD", provider="HistData", rights_confirmed=True)


def test_clean_archive_only_becomes_ready_when_all_rows_accepted(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, "20261001 090000;1;2;0.5;1.5;0\n"
                          "20261001 090100;2;3;1;2.5;0\n")
    result = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData",
                    rights_confirmed=True)
    assert (result["state"], result["accepted"], result["rejected"]) == ("READY", 2, 0)


def test_empty_archive_is_quarantined_not_ready(tmp_path):
    e = engine(tmp_path)
    p = archive(tmp_path, "")
    result = ingest(e, p, instrument="XAUUSD-CFD", provider="HistData",
                    rights_confirmed=True)
    assert (result["state"], result["accepted"], result["rejected"]) == ("QUARANTINED", 0, 0)
