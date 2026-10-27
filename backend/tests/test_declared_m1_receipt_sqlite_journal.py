"""Synthetic local-only tests for declared M1 receipt checkpoint storage."""
import json
import sqlite3

import pytest

from app.expected_bar_manifest import compile_expected_m1_manifest
from app.declared_m1_receipt_sqlite_journal import (
    append_declared_m1_checkpoint, read_declared_m1_checkpoint_head,
)

T = 1790000040
ZERO = "0" * 64
BASE = dict(provider="fixture", symbol="XAU/USD", venue="synthetic",
            price_side="BID", calendar_id="fixture", calendar_revision="r1",
            calendar_source="operator declared UTC schedule", exclusions_utc=[])


def manifest(now, sessions, **kw):
    return compile_expected_m1_manifest(
        **(BASE | dict(observed_at_utc=now, sessions_utc=sessions) | kw))


def bar(t, **kw):
    return dict(dict(provider="fixture", symbol="XAU/USD", venue="synthetic",
                     price_side="BID", bar_start_utc=t, received_at_utc=t + 65,
                     open=100., high=102., low=99., close=101.) | kw)


P = manifest(T + 180, [(T, T + 120)])
C = manifest(T + 300, [(T, T + 120), (T + 180, T + 240)])
OLD = [bar(T), bar(T + 60)]
NEW = OLD + [bar(T + 180)]


def test_genesis_append_read_and_continuity(tmp_path):
    path = tmp_path / "m1.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    assert first["status"] == "DECLARED_CHECKPOINT_LOCALLY_COMMITTED"
    assert first["revision"] == 1 and first["live"] is False
    second = append_declared_m1_checkpoint(
        path, NEW, C, first["checkpoint_sha256"])
    assert second["revision"] == 2
    assert second["previous_checkpoint_sha256"] == first["checkpoint_sha256"]
    assert second["source_authenticated"] is False
    assert second["may_execute_order"] is False
    read = read_declared_m1_checkpoint_head(path, P)
    assert read["checkpoint_sha256"] == second["checkpoint_sha256"]
    assert read["status"] == "LOCAL_DECLARED_CHAIN_ONLY_NOT_LIVE"


def test_idempotent_genesis_retry_and_stale_writer_rejected(tmp_path):
    path = tmp_path / "m1.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    retry = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    assert retry["status"] == "IDEMPOTENT_DECLARED_RETRY"
    assert retry["checkpoint_sha256"] == first["checkpoint_sha256"]
    append_declared_m1_checkpoint(path, NEW, C, first["checkpoint_sha256"])
    with pytest.raises(ValueError, match="compare-and-swap"):
        append_declared_m1_checkpoint(path, OLD, P, ZERO)
    assert read_declared_m1_checkpoint_head(path, P)["revision"] == 2


@pytest.mark.parametrize("rows", [
    [bar(T, close=100.5), bar(T + 60), bar(T + 180)],
    [bar(T), bar(T + 180)],
    [bar(T), bar(T + 60, received_at_utc=T + 126), bar(T + 180)],
    [bar(T), bar(T + 60), bar(T + 180, received_at_utc=T + 239)],
])
def test_revisions_removal_or_backdated_receipt_do_not_append(tmp_path, rows):
    path = tmp_path / "m1.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    with pytest.raises(ValueError):
        append_declared_m1_checkpoint(path, rows, C, first["checkpoint_sha256"])
    assert read_declared_m1_checkpoint_head(path, P)["revision"] == 1


def test_invalid_genesis_and_bounded_path_rejected(tmp_path):
    path = tmp_path / "m1.db"
    with pytest.raises(ValueError):
        append_declared_m1_checkpoint(path, OLD, P, "f" * 64)
    with pytest.raises(ValueError):
        append_declared_m1_checkpoint(":memory:", OLD, P, ZERO)
    with pytest.raises(ValueError):
        append_declared_m1_checkpoint(path, OLD, P, "not-a-sha")
    with pytest.raises(ValueError):
        read_declared_m1_checkpoint_head(tmp_path / "missing.db", P)


def test_retroactive_closed_session_rejected(tmp_path):
    path = tmp_path / "m1.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    after = manifest(T + 300, [(T, T + 120), (T + 120, T + 180)],
                     exclusions_utc=[(T + 120, T + 180)])
    with pytest.raises(ValueError, match="continuity"):
        append_declared_m1_checkpoint(path, OLD, after, first["checkpoint_sha256"])
    assert read_declared_m1_checkpoint_head(path, P)["revision"] == 1


def test_tampered_stored_price_detected_even_with_unchanged_head(tmp_path):
    path = tmp_path / "m1.db"
    append_declared_m1_checkpoint(path, OLD, P, ZERO)
    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT payload_json FROM declared_m1_snapshots").fetchone()[0]
        payload = json.loads(raw)
        payload["receipts"][0]["close"] = 100.5
        conn.execute(
            "UPDATE declared_m1_snapshots SET payload_json=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),))
    with pytest.raises(ValueError, match="hash mismatch"):
        read_declared_m1_checkpoint_head(path, P)


def test_deleted_snapshot_detected(tmp_path):
    path = tmp_path / "m1.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    append_declared_m1_checkpoint(path, NEW, C, first["checkpoint_sha256"])
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM declared_m1_snapshots WHERE revision=1")
    with pytest.raises(ValueError, match="stored receipt chain"):
        read_declared_m1_checkpoint_head(path, P)


def test_changed_stored_calendar_population_detected(tmp_path):
    path = tmp_path / "m1.db"
    append_declared_m1_checkpoint(path, OLD, P, ZERO)
    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT payload_json FROM declared_m1_snapshots").fetchone()[0]
        payload = json.loads(raw)
        payload["manifest"]["expected_minutes"].pop()
        conn.execute(
            "UPDATE declared_m1_snapshots SET payload_json=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),))
    with pytest.raises(ValueError, match="manifest"):
        read_declared_m1_checkpoint_head(path, P)


def test_different_source_cannot_reuse_chain(tmp_path):
    path = tmp_path / "m1.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    changed = manifest(T + 300, [(T, T + 120), (T + 180, T + 240)],
                       price_side="ASK")
    with pytest.raises(ValueError):
        append_declared_m1_checkpoint(path, NEW, changed, first["checkpoint_sha256"])
