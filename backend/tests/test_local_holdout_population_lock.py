"""Synthetic-only local population overlap tests; no market or broker calls."""
from concurrent.futures import ThreadPoolExecutor
import copy
import sqlite3

import pytest

from app import local_holdout_release_registry as registry
from app.local_holdout_population_lock import register_population_locked_holdout, _ROW_SCHEMA, _source_key
from app.declared_holdout_release_gate import (
    prepare_declared_holdout_census_sha256,
    prepare_declared_holdout_manifest_sha256,
)


@pytest.fixture
def clock(monkeypatch):
    value = [1251]
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: value[0])
    return value


def _study(study="one", offset=0, source="a", candidate="frozen", decision_offset=0):
    census = [dict(observation_id=f"o{i}", row_sha256=f"{offset + i + 1:064x}",
                   source_sha256=source * 64, decision_at_utc=2100 + decision_offset + i * 100,
                   label_available_at_utc=2150 + decision_offset + i * 100)
              for i in range(35)]
    manifest = dict(study_id=study, candidate_id=candidate,
                    candidate_config_sha256="b" * 64,
                    selection_evidence_sha256="c" * 64,
                    validation_end_at_utc=1000, selected_at_utc=1200,
                    registered_at_utc=1250, holdout_start_at_utc=2000,
                    holdout_end_at_utc=20000, embargo_seconds=100,
                    expected_holdout_count=len(census),
                    holdout_census_sha256=prepare_declared_holdout_census_sha256(census),
                    source=dict(provider="Synthetic", venue="Demo", instrument="XAUUSD-CFD",
                                quote_side="BID", account_alias="test-1",
                                settlement_currency="GBP", utc_convention="UTC",
                                archive_sha256=source * 64))
    return manifest, census


def test_register_and_release_with_existing_one_attempt_gate(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    manifest, census = _study()
    result = register_population_locked_holdout(path, manifest, census)
    assert result["locked_observation_count"] == 35
    assert result["locked_decision_count"] == 35
    assert result["independently_trusted_registry"] is False
    assert result["manifest_sha256"] == prepare_declared_holdout_manifest_sha256(manifest)
    clock[0] = 20001
    assert registry.claim_local_holdout_release(
        path, study_id="one", manifest_sha256=result["manifest_sha256"]
    )["local_one_attempt_claim_recorded"] is True
    with pytest.raises(ValueError, match="already claimed"):
        registry.claim_local_holdout_release(
            path, study_id="one", manifest_sha256=result["manifest_sha256"])


def test_same_population_different_candidate_or_study_rejected(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, rows = _study()
    register_population_locked_holdout(path, first, rows)
    second, same_rows = _study(study="two", candidate="other")
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, second, same_rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)


def test_partial_overlap_rejected_and_transaction_rolled_back(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, rows = _study()
    register_population_locked_holdout(path, first, rows)
    second, overlapping = _study(study="two", offset=100, decision_offset=5000)
    # A late collision verifies that earlier inserted rows are rolled back.
    overlapping[20]["row_sha256"] = rows[0]["row_sha256"]
    second["holdout_census_sha256"] = prepare_declared_holdout_census_sha256(overlapping)
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, second, overlapping)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims WHERE study_id='two'").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)
    # A failed overlapping registration must not leave a partial claim.
    disjoint, other_rows = _study(study="two", offset=100, decision_offset=5000)
    assert register_population_locked_holdout(path, disjoint, other_rows)["locked_observation_count"] == 35


def test_disjoint_population_or_distinct_declared_feed_allowed(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, rows = _study()
    register_population_locked_holdout(path, first, rows)
    disjoint, new_rows = _study(study="two", offset=100, decision_offset=5000)
    register_population_locked_holdout(path, disjoint, new_rows)
    other_source, same_hash_rows = _study(study="three", source="d")
    other_source["source"]["provider"] = "DifferentVendor"
    register_population_locked_holdout(path, other_source, same_hash_rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (105,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_decisions").fetchone() == (105,)


def test_duplicate_study_and_malformed_census_fail_closed(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    manifest, census = _study()
    register_population_locked_holdout(path, manifest, census)
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, manifest, census)
    bad_manifest, bad_census = _study(study="two", offset=100)
    bad_census[0]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        register_population_locked_holdout(path, bad_manifest, bad_census)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)


def test_early_registration_rejected(tmp_path, clock):
    clock[0] = 2000
    with pytest.raises(ValueError, match="precede"):
        register_population_locked_holdout(tmp_path / "locked.sqlite", *_study())


def test_two_concurrent_overlapping_studies_exactly_one_registered(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first = _study(study="one")
    second = _study(study="two", candidate="other")
    def attempt(data):
        try:
            return register_population_locked_holdout(path, *data)["study_id"]
        except sqlite3.IntegrityError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(attempt, (first, second)))
    assert sum(x is not None for x in winners) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)


def test_reordered_or_mutated_census_cannot_reuse_old_commitment(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    manifest, census = _study()
    changed = copy.deepcopy(census)
    changed.reverse()
    with pytest.raises(ValueError):
        register_population_locked_holdout(path, manifest, changed)
    changed = copy.deepcopy(census)
    changed[0]["row_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        register_population_locked_holdout(path, manifest, changed)
    assert not path.exists()


def test_same_rows_different_archive_or_account_still_rejected(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, rows = _study()
    register_population_locked_holdout(path, first, rows)
    other_archive, same_rows = _study(study="two", source="d")
    # An archive split with the same declared market feed must not reset the lock.
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, other_archive, same_rows)
    other_account, same_rows = _study(study="three")
    other_account["source"]["account_alias"] = "another-account"
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, other_account, same_rows)


def test_legacy_registration_rejected_after_population_lock(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    manifest, census = _study()
    register_population_locked_holdout(path, manifest, census)
    with pytest.raises(ValueError, match="rejects legacy registration"):
        registry.register_local_holdout(
            path, study_id="legacy", manifest_sha256="f" * 64,
            holdout_start_at_utc=2000, holdout_end_at_utc=20000)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)


def test_preexisting_legacy_registration_blocks_first_population_lock(tmp_path, clock):
    path = tmp_path / "legacy.sqlite"
    registry.register_local_holdout(
        path, study_id="legacy", manifest_sha256="f" * 64,
        holdout_start_at_utc=2000, holdout_end_at_utc=20000)
    manifest, census = _study(study="new", offset=100)
    with pytest.raises(ValueError, match="Legacy unreserved holdout claims"):
        register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND name='holdout_locked_rows'"
        ).fetchone() == (0,)


def test_revised_row_hashes_cannot_reuse_same_feed_decision_times(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, original = _study()
    register_population_locked_holdout(path, first, original)
    revised, rows = _study(study="revised", offset=100)
    # All hashes differ but the same source and decision timestamps are reused.
    assert {r["row_sha256"] for r in original}.isdisjoint(
        {r["row_sha256"] for r in rows})
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, revised, rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_decisions").fetchone() == (35,)


def test_single_late_decision_collision_rolls_back_both_reservations(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, original = _study()
    register_population_locked_holdout(path, first, original)
    second, rows = _study(study="revised", offset=100, decision_offset=5000)
    rows[-1]["decision_at_utc"] = original[0]["decision_at_utc"]
    # Keep the census chronological while colliding with a previous study.
    rows.sort(key=lambda r: r["decision_at_utc"])
    second["holdout_census_sha256"] = prepare_declared_holdout_census_sha256(rows)
    with pytest.raises(sqlite3.IntegrityError):
        register_population_locked_holdout(path, second, rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_decisions").fetchone() == (35,)


def test_existing_row_only_registry_requires_explicit_clean_database(tmp_path, clock):
    path = tmp_path / "old.sqlite"
    manifest, census = _study()
    with sqlite3.connect(path) as conn:
        conn.execute(registry._SCHEMA)
        conn.execute(_ROW_SCHEMA)
        conn.execute(
            "INSERT INTO holdout_claims VALUES (?, ?, ?, ?, ?, NULL)",
            ("old", "a" * 64, 2000, 20000, 1251))
        conn.execute(
            "INSERT INTO holdout_locked_rows VALUES (?, ?, ?)",
            (_source_key(manifest["source"]), census[0]["row_sha256"], "old"))
    fresh, rows = _study(study="fresh", offset=100, decision_offset=5000)
    with pytest.raises(ValueError, match="lacks decision-time reservations"):
        register_population_locked_holdout(path, fresh, rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='holdout_locked_decisions'"
        ).fetchone() == (0,)


def test_incomplete_timestamp_reservation_population_rejected(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, original = _study()
    register_population_locked_holdout(path, first, original)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM holdout_locked_decisions WHERE decision_at_utc=?", (2100,))
    fresh, rows = _study(study="fresh", offset=100, decision_offset=5000)
    with pytest.raises(ValueError, match="Incomplete row or decision-time"):
        register_population_locked_holdout(path, fresh, rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_decisions").fetchone() == (34,)


def test_future_dated_declared_registration_is_rejected_without_creating_db(tmp_path, clock):
    path = tmp_path / "future.sqlite"
    manifest, census = _study()
    # Local clock 1249 precedes the declared registration at 1250, although
    # both timestamps are before the holdout start. This is not valid evidence.
    clock[0] = 1249
    with pytest.raises(ValueError, match="precedes declared registration"):
        register_population_locked_holdout(path, manifest, census)
    assert not path.exists()


def test_registration_at_declared_time_allowed_and_future_claim_preserves_db(tmp_path, clock):
    path = tmp_path / "locked.sqlite"
    first, rows = _study()
    clock[0] = first["registered_at_utc"]
    assert register_population_locked_holdout(path, first, rows)["locked_observation_count"] == 35
    second, other_rows = _study(study="second", offset=100, decision_offset=5000)
    second["registered_at_utc"] = clock[0] + 1
    with pytest.raises(ValueError, match="precedes declared registration"):
        register_population_locked_holdout(path, second, other_rows)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_decisions").fetchone() == (35,)
