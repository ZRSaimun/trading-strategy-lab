"""Synthetic archive mutation checks; no licensed data or production writes."""
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from sqlalchemy import create_engine, select

from app import bulk_import


def _sample(tmp_path):
    path = tmp_path / "immutable.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("source.csv", "20261001 090000;1;2;0.5;1.5;0\n"
                                 "20261001 090100;2;3;1;2.5;0\n")
    engine = create_engine("sqlite:///" + str(tmp_path / "history.sqlite"))
    bulk_import.create_schema(engine)
    return path, engine


def _ingest(engine, path, **kwargs):
    return bulk_import.ingest(engine, path, instrument="XAUUSD-CFD",
                              provider="Synthetic", rights_confirmed=True, **kwargs)


def test_clean_archive_identity_is_checked_again_before_ready(tmp_path, monkeypatch):
    path, engine = _sample(tmp_path)
    original = bulk_import.sha256_file
    observed = []

    def spy(source):
        observed.append(source)
        return original(source)

    monkeypatch.setattr(bulk_import, "sha256_file", spy)
    result = _ingest(engine, path)
    assert result["state"] == "READY"
    assert len(observed) == 2
    assert observed == [path, path]


def test_changed_zip_fails_closed_and_retains_private_checkpoint(tmp_path, monkeypatch):
    path, engine = _sample(tmp_path)
    original = bulk_import.sha256_file
    hashes = []

    def changed(source):
        hashes.append(source)
        return original(source) if len(hashes) == 1 else "f" * 64

    monkeypatch.setattr(bulk_import, "sha256_file", changed)
    with pytest.raises(ValueError, match="Archive bytes changed during import"):
        _ingest(engine, path, chunk_rows=1)
    assert len(hashes) == 2
    with engine.connect() as conn:
        dataset = conn.execute(select(bulk_import.datasets)).mappings().one()
        assert dataset["state"] == "FAILED"
        assert dataset["accepted"] == 2
        assert dataset["rejected"] == 0
        assert dataset["seen"] == 2
        assert "Archive bytes changed" in dataset["error"]


def test_changed_zip_on_resume_never_becomes_ready(tmp_path, monkeypatch):
    path, engine = _sample(tmp_path)
    paused = _ingest(engine, path, chunk_rows=1, max_rows_per_run=1)
    assert paused["state"] == "IMPORTING"
    original = bulk_import.sha256_file
    calls = []

    def changed(source):
        calls.append(source)
        return original(source) if len(calls) == 1 else "e" * 64

    monkeypatch.setattr(bulk_import, "sha256_file", changed)
    with pytest.raises(ValueError, match="Archive bytes changed during import"):
        _ingest(engine, path, chunk_rows=1)
    with engine.connect() as conn:
        dataset = conn.execute(select(bulk_import.datasets)).mappings().one()
        assert dataset["state"] == "FAILED"
        assert dataset["seen"] == 2
        assert dataset["accepted"] == 2
