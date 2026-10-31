"""Synthetic oversized-row regressions; no vendor archives or network calls."""
import hashlib
import io
from zipfile import ZipFile, ZIP_DEFLATED

from sqlalchemy import create_engine, func, select

from app import bulk_import


def _archive(tmp_path, raw):
    path = tmp_path / "oversized.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("source.csv", raw)
    engine = create_engine("sqlite:///" + str(tmp_path / "disposable.sqlite"))
    bulk_import.create_schema(engine)
    return path, engine


def _ingest(engine, path, **kwargs):
    return bulk_import.ingest(
        engine, path, instrument="XAUUSD-CFD", provider="Synthetic",
        rights_confirmed=True, chunk_rows=1, **kwargs,
    )


def test_bounded_reader_preserves_following_row_after_large_line(tmp_path):
    for newline in ("\n", "\r\n", "\r"):
        raw = ("X" * 1_000_000 + newline +
               "20261001 090000;1;2;0.5;1.5;0" + newline)
        stream = io.TextIOWrapper(io.BytesIO(raw.encode()), newline=None)
        lines = list(bulk_import._bounded_source_lines(stream))
        assert len(lines) == 2
        assert lines[0][1] is True
        assert len(lines[0][0]) == 1025
        assert lines[1][1] is False
        assert lines[1][0].startswith("20261001 090000")


def test_reader_requests_bounded_reads_even_when_discarding():
    class GuardedReader(io.StringIO):
        def readline(self, size=-1):
            assert 0 < size <= 1025, "unbounded readline would allocate a huge row"
            return super().readline(size)

    rows = list(bulk_import._bounded_source_lines(
        GuardedReader("X" * 100_000 + "\n" + "valid\n")
    ))
    assert rows[0][1] and len(rows[0][0]) == 1025
    assert rows[1] == ("valid\n", False)


def test_oversized_zip_row_quarantined_and_next_row_retained(tmp_path):
    raw = "X" * 1_000_000 + "\r\n20261001 090000;1;2;0.5;1.5;0\r\n"
    path, engine = _archive(tmp_path, raw)
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    result = _ingest(engine, path)
    assert (result["state"], result["accepted"], result["rejected"]) == (
        "QUARANTINED", 1, 1
    )
    with engine.connect() as connection:
        row = connection.execute(select(bulk_import.datasets)).mappings().one()
        assert row["seen"] == 2 and row["checkpoint_member"] == 1
        assert row["archive_sha256"] == original
        assert connection.scalar(select(func.count()).select_from(bulk_import.candles)) == 1
        issue = connection.execute(select(bulk_import.issues)).mappings().one()
        assert issue["line"] == 1 and issue["reason"] == "row too long"
        assert len(issue["sample"]) <= 300
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def test_pause_resume_after_oversized_row_keeps_original_ordinals(tmp_path):
    raw = "X" * 1_000_000 + "\n20261001 090000;1;2;0.5;1.5;0\n"
    path, engine = _archive(tmp_path, raw)
    first = _ingest(engine, path, max_rows_per_run=1)
    assert first["state"] == "IMPORTING" and first["paused"] is True
    final = _ingest(engine, path)
    assert (final["state"], final["accepted"], final["rejected"]) == (
        "QUARANTINED", 1, 1
    )
    with engine.connect() as connection:
        row = connection.execute(select(bulk_import.datasets)).mappings().one()
        assert row["seen"] == 2
        assert connection.scalar(select(func.count()).select_from(bulk_import.candles)) == 1
        issue = connection.execute(select(bulk_import.issues)).mappings().one()
        assert issue["line"] == 1
