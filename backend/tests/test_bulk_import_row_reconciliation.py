"""Synthetic stored-row reconciliation tests; never use licensed market data."""
from zipfile import ZipFile, ZIP_DEFLATED

from sqlalchemy import create_engine, delete, func, select

from app import bulk_import


def _setup(tmp_path):
    archive = tmp_path / "clean-synthetic.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        z.writestr("source.csv",
                   "20261001 090000;1;2;0.5;1.5;0\n"
                   "20261001 090100;2;3;1;2.5;0\n")
    engine = create_engine("sqlite:///" + str(tmp_path / "staging.sqlite"))
    bulk_import.create_schema(engine)
    return archive, engine


def _ingest(engine, archive, **kwargs):
    return bulk_import.ingest(
        engine, archive, instrument="XAUUSD-TEST", provider="Synthetic",
        rights_confirmed=True, chunk_rows=2, **kwargs,
    )


def _dataset(engine):
    with engine.connect() as connection:
        row = connection.execute(select(bulk_import.datasets)).mappings().one()
        count = connection.scalar(select(func.count()).select_from(bulk_import.candles))
    return row, count


def test_clean_archive_still_ready_when_rows_reconcile(tmp_path):
    archive, engine = _setup(tmp_path)
    result = _ingest(engine, archive)
    row, count = _dataset(engine)
    assert result["state"] == "READY"
    assert (row["seen"], row["accepted"], row["rejected"], count) == (2, 2, 0, 2)


def test_skipped_insert_does_not_publish_ready(tmp_path, monkeypatch):
    archive, engine = _setup(tmp_path)
    original = bulk_import._bulk_insert

    def silently_drop_one(connection, rows, table):
        if table is bulk_import.candles and len(rows) == 2:
            return original(connection, rows[:1], table)
        return original(connection, rows, table)

    monkeypatch.setattr(bulk_import, "_bulk_insert", silently_drop_one)
    result = _ingest(engine, archive)
    row, count = _dataset(engine)
    assert result["state"] == row["state"] == "QUARANTINED"
    assert (row["seen"], row["accepted"], row["rejected"], count) == (2, 2, 0, 1)
    assert "Stored candle count" in row["error"]


def test_resume_with_missing_checkpoint_row_is_quarantined(tmp_path):
    archive, engine = _setup(tmp_path)
    paused = bulk_import.ingest(
        engine, archive, instrument="XAUUSD-TEST", provider="Synthetic",
        rights_confirmed=True, chunk_rows=1, max_rows_per_run=1,
    )
    assert paused["state"] == "IMPORTING"
    with engine.begin() as connection:
        connection.execute(delete(bulk_import.candles))
    result = _ingest(engine, archive)
    row, count = _dataset(engine)
    assert result["state"] == "QUARANTINED"
    assert (row["accepted"], row["seen"], count) == (2, 2, 1)


def test_existing_ready_is_downgraded_on_reimport_if_rows_missing(tmp_path):
    archive, engine = _setup(tmp_path)
    assert _ingest(engine, archive)["state"] == "READY"
    with engine.begin() as connection:
        connection.execute(delete(bulk_import.candles).where(
            bulk_import.candles.c.source_line == 2))
    result = _ingest(engine, archive)
    row, count = _dataset(engine)
    assert result["state"] == "QUARANTINED"
    assert result["already_complete"] is True
    assert row["state"] == "QUARANTINED"
    assert "Stored candle count" in row["error"]
    assert count == 1
    # An identical archive cannot silently recover this quarantined identity.
    assert _ingest(engine, archive)["state"] == "QUARANTINED"
