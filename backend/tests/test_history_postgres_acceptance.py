"""Disposable PostgreSQL acceptance for historical ZIP ingestion and API visibility.

Synthetic candles only. Never point this at an existing database. Every test
creates a random isolated schema in a loopback-only *_test PostgreSQL database.
"""
import os
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import make_url

from app import bulk_import
from app.historical_api import attach_history


@pytest.fixture
def pg_history(tmp_path):
    url = os.getenv("TSL_PG_HISTORY_TEST_URL")
    if not url:
        pytest.skip("Disposable historical PostgreSQL test database not configured")
    parsed = make_url(url)
    if (parsed.get_backend_name() != "postgresql"
            or parsed.host not in ("127.0.0.1", "localhost", "::1")
            or not parsed.database or not parsed.database.endswith("_test")):
        pytest.fail("Refusing historical acceptance outside loopback *_test database")
    schema = "history_accept_" + uuid4().hex
    admin = create_engine(url, pool_pre_ping=True)
    with admin.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = create_engine(
        url, pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=2, max_overflow=0,
    )
    try:
        bulk_import.create_schema(isolated)
        yield isolated, tmp_path
    finally:
        isolated.dispose()
        try:
            with admin.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def _archive(tmp_path, rows, name="source.zip"):
    path = tmp_path / name
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("source.csv", rows)
    return path


def _ingest(engine, path, **kwargs):
    return bulk_import.ingest(
        engine, path, instrument="XAUUSD-TEST", provider="Synthetic",
        rights_confirmed=True, **kwargs,
    )


def _client(engine, *, authenticated=True):
    app = FastAPI()
    def owner():
        if not authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")
        return "synthetic-owner"
    app.include_router(attach_history(owner, engine))
    return TestClient(app)


CLEAN = ("20261001 090000;1;2;0.5;1.5;0\n"
         "20261001 090100;2;3;1;2.5;0\n")


def test_postgres_clean_import_is_ready_and_explicitly_historical(pg_history):
    engine, tmp_path = pg_history
    path = _archive(tmp_path, CLEAN)
    result = _ingest(engine, path, chunk_rows=1)
    assert (result["state"], result["accepted"], result["rejected"]) == ("READY", 2, 0)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(bulk_import.candles)) == 2
    client = _client(engine)
    listed = client.get("/api/history/datasets")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [result["dataset_id"]]
    response = client.get(f'/api/history/{result["dataset_id"]}/candles',
                          params={"timeframe": "1m"})
    assert response.status_code == 200, response.text
    assert len(response.json()["candles"]) == 2
    assert response.json()["quality"]["live"] is False
    assert response.json()["quality"]["state"] == "HISTORICAL ONLY"
    assert response.json()["dataset"]["archive_sha256"] == bulk_import.sha256_file(path)
    assert _client(engine, authenticated=False).get("/api/history/datasets").status_code == 401
    assert _client(engine, authenticated=False).get(
        f'/api/history/{result["dataset_id"]}/candles').status_code == 401


def test_postgres_conflicting_timestamp_is_quarantined_and_hidden(pg_history):
    engine, tmp_path = pg_history
    path = _archive(tmp_path, CLEAN + "20261001 090100;8;9;7;8.5;0\n")
    result = _ingest(engine, path, chunk_rows=1)
    assert (result["state"], result["accepted"], result["rejected"]) == ("QUARANTINED", 2, 1)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(bulk_import.candles)) == 2
        assert conn.scalar(select(func.count()).select_from(bulk_import.issues)) == 1
    client = _client(engine)
    assert client.get("/api/history/datasets").json() == []
    assert client.get(f'/api/history/{result["dataset_id"]}/candles').status_code == 404
    assert _ingest(engine, path)["state"] == "QUARANTINED"


def test_postgres_resume_with_missing_stored_row_fails_closed(pg_history):
    engine, tmp_path = pg_history
    path = _archive(tmp_path, CLEAN)
    paused = _ingest(engine, path, chunk_rows=1, max_rows_per_run=1)
    assert paused["state"] == "IMPORTING"
    assert _client(engine).get("/api/history/datasets").json() == []
    with engine.begin() as conn:
        conn.execute(delete(bulk_import.candles))
    result = _ingest(engine, path, chunk_rows=1)
    assert result["state"] == "QUARANTINED"
    with engine.connect() as conn:
        row = conn.execute(select(bulk_import.datasets)).mappings().one()
        assert (row["accepted"], row["seen"], row["rejected"]) == (2, 2, 0)
        assert "Stored candle count" in row["error"]
    assert _client(engine).get(f'/api/history/{result["dataset_id"]}/candles').status_code == 404


def test_postgres_changed_archive_digest_cannot_become_ready(pg_history, monkeypatch):
    engine, tmp_path = pg_history
    path = _archive(tmp_path, CLEAN)
    original = bulk_import.sha256_file
    checks = []
    def digest(source):
        checks.append(source)
        return original(source) if len(checks) == 1 else "f" * 64
    monkeypatch.setattr(bulk_import, "sha256_file", digest)
    with pytest.raises(ValueError, match="Archive bytes changed during import"):
        _ingest(engine, path, chunk_rows=1)
    assert len(checks) == 2
    with engine.connect() as conn:
        row = conn.execute(select(bulk_import.datasets)).mappings().one()
        assert row["state"] == "FAILED"
        assert row["accepted"] == 2
    assert _client(engine).get("/api/history/datasets").json() == []


def test_postgres_existing_ready_missing_row_downgrades_on_recheck(pg_history):
    engine, tmp_path = pg_history
    path = _archive(tmp_path, CLEAN)
    result = _ingest(engine, path)
    assert result["state"] == "READY"
    with engine.begin() as conn:
        conn.execute(delete(bulk_import.candles).where(
            bulk_import.candles.c.source_line == 2))
    again = _ingest(engine, path)
    assert again["state"] == "QUARANTINED"
    with engine.connect() as conn:
        row = conn.execute(select(bulk_import.datasets)).mappings().one()
        assert row["state"] == "QUARANTINED"
    assert _client(engine).get("/api/history/datasets").json() == []


def test_postgres_history_dump_restore_and_rollback_in_disposable_database(pg_history):
    """Exercise real pg_dump/pg_restore on synthetic archives, never owner data.

    The existing fixture has already validated loopback and *_test, and uses
    a randomly named isolated schema. The restore database is newly created
    with a random *_test name and is dropped in a finally block.
    """
    import shutil
    import subprocess

    if not shutil.which("pg_dump") or not shutil.which("pg_restore"):
        pytest.fail("PostgreSQL client pg_dump/pg_restore required for recovery acceptance")

    engine, tmp_path = pg_history
    source = make_url(os.environ["TSL_PG_HISTORY_TEST_URL"])
    assert source.host in ("127.0.0.1", "localhost", "::1")
    assert source.database.endswith("_test")
    with engine.connect() as connection:
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    assert schema.startswith("history_accept_")

    clean = _ingest(engine, _archive(tmp_path, CLEAN, name="clean.zip"))
    bad = _ingest(engine, _archive(
        tmp_path, CLEAN + "20261001 090100;8;9;7;8.5;0\n", name="conflict.zip"))
    assert clean["state"] == "READY" and bad["state"] == "QUARANTINED"

    def snapshot(target):
        with target.connect() as connection:
            return {
                "datasets": [tuple(row) for row in connection.execute(
                    select(bulk_import.datasets).order_by(bulk_import.datasets.c.id))],
                "candles": [tuple(row) for row in connection.execute(
                    select(bulk_import.candles).order_by(
                        bulk_import.candles.c.dataset_id, bulk_import.candles.c.time))],
                "issues": [tuple(row) for row in connection.execute(
                    select(bulk_import.issues).order_by(
                        bulk_import.issues.c.dataset_id, bulk_import.issues.c.line))],
            }

    expected = snapshot(engine)
    assert len(expected["datasets"]) == 2
    assert len(expected["candles"]) == 4
    assert len(expected["issues"]) == 1

    # Password is only supplied through subprocess environment, never argv.
    pg_env = os.environ.copy()
    pg_env.update(PGHOST=source.host, PGPORT=str(source.port or 5432),
                  PGUSER=source.username or "postgres", PGPASSWORD=source.password or "")
    dump = tmp_path / "synthetic-history.dump"
    def pg_command(*args):
        result = subprocess.run(args, env=pg_env, capture_output=True, timeout=45,
                                check=False)
        if result.returncode:
            # Do not expose pg_dump stderr or connection credentials in CI.
            pytest.fail("Disposable PostgreSQL dump/restore command failed")

    pg_command("pg_dump", "--format=custom", "--no-owner", "--no-acl",
               "--schema=" + schema, "--file=" + str(dump), source.database)
    assert dump.is_file() and dump.stat().st_size > 0
    dump.chmod(0o600)

    restore_name = "history_restore_" + uuid4().hex + "_test"
    restore_url = source.set(database=restore_name).render_as_string(hide_password=False)
    admin = create_engine(os.environ["TSL_PG_HISTORY_TEST_URL"])
    restored = None
    created = False
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{restore_name}"')
        created = True
        pg_command("pg_restore", "--exit-on-error", "--single-transaction",
                   "--no-owner", "--no-acl", "--dbname=" + restore_name, str(dump))
        restored = create_engine(restore_url,
                                 connect_args={"options": f"-csearch_path={schema}"})
        assert snapshot(restored) == expected
        assert [item["id"] for item in _client(restored).get(
            "/api/history/datasets").json()] == [clean["dataset_id"]]
        assert _client(restored).get(
            f'/api/history/{bad["dataset_id"]}/candles').status_code == 404
        assert _client(restored, authenticated=False).get(
            "/api/history/datasets").status_code == 401

        # Deliberately corrupt only the newly created disposable restore DB.
        with restored.begin() as connection:
            connection.execute(bulk_import.datasets.update().where(
                bulk_import.datasets.c.id == clean["dataset_id"]
            ).values(state="QUARANTINED"))
            connection.execute(delete(bulk_import.candles).where(
                bulk_import.candles.c.dataset_id == clean["dataset_id"]))
        assert snapshot(restored) != expected
        assert _client(restored).get("/api/history/datasets").json() == []
        restored.dispose()
        restored = None

        # A second restore acts as a rollback to the immutable backup.
        pg_command("pg_restore", "--clean", "--if-exists", "--exit-on-error",
                   "--single-transaction", "--no-owner", "--no-acl",
                   "--dbname=" + restore_name, str(dump))
        restored = create_engine(restore_url,
                                 connect_args={"options": f"-csearch_path={schema}"})
        assert snapshot(restored) == expected
        assert [item["id"] for item in _client(restored).get(
            "/api/history/datasets").json()] == [clean["dataset_id"]]
    finally:
        if restored is not None:
            restored.dispose()
        if created:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{restore_name}" WITH (FORCE)')
        admin.dispose()
