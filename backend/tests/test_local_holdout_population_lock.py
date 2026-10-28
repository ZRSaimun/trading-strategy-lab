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
    # A direct claim without the frozen census must not consume the only
    # release attempt for a population-locked study.
    with pytest.raises(ValueError, match="requires exact frozen census"):
        registry.claim_local_holdout_release(
            path, study_id="one", manifest_sha256=result["manifest_sha256"])
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id='one'"
        ).fetchone() == (None,)

    frozen = {
        "expected_population_rows": [
            (r["row_sha256"], r["decision_at_utc"]) for r in census
        ],
        "expected_source_key_sha256": _source_key(manifest["source"]),
    }
    claim = registry.claim_local_holdout_release(
        path, study_id="one", manifest_sha256=result["manifest_sha256"], **frozen)
    assert claim["local_one_attempt_claim_recorded"] is True
    assert claim["local_frozen_population_matched"] is True
    with pytest.raises(ValueError, match="already claimed"):
        registry.claim_local_holdout_release(
            path, study_id="one", manifest_sha256=result["manifest_sha256"], **frozen)


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


@pytest.mark.parametrize("corruption", [
    "missing_decision", "missing_all", "orphan_row", "orphan_decision",
    "dropped_decision_table",
])
def test_release_rejects_corrupted_population_reservations_without_consuming_claim(
        tmp_path, clock, corruption):
    path = tmp_path / "release-integrity.sqlite"
    manifest, census = _study()
    registered = register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        if corruption == "missing_decision":
            conn.execute("DELETE FROM holdout_locked_decisions WHERE decision_at_utc=2100")
        elif corruption == "missing_all":
            conn.execute("DELETE FROM holdout_locked_rows WHERE study_id='one'")
            conn.execute("DELETE FROM holdout_locked_decisions WHERE study_id='one'")
        elif corruption == "orphan_row":
            conn.execute(
                "INSERT INTO holdout_locked_rows VALUES (?, ?, ?)",
                (_source_key(manifest["source"]), "f" * 64, "ghost"))
        elif corruption == "orphan_decision":
            conn.execute(
                "INSERT INTO holdout_locked_decisions VALUES (?, ?, ?)",
                (_source_key(manifest["source"]), 9999, "ghost"))
        else:
            conn.execute("DROP TABLE holdout_locked_decisions")
    clock[0] = manifest["holdout_end_at_utc"] + 1
    with pytest.raises(ValueError, match="Incomplete population|Orphaned population"):
        registry.claim_local_holdout_release(
            path, study_id="one", manifest_sha256=registered["manifest_sha256"])
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id='one'"
        ).fetchone() == (None,)


@pytest.mark.parametrize("corruption", [
    "decision_after_end", "decision_text", "split_source", "orphan_row",
])
def test_balanced_corruption_blocks_new_registration_and_release(
        tmp_path, clock, corruption):
    """Counts may remain equal while decision/feed lineage is corrupt."""
    path = tmp_path / "balanced-corruption.sqlite"
    manifest, census = _study()
    registration = register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        if corruption == "decision_after_end":
            conn.execute(
                "UPDATE holdout_locked_decisions SET decision_at_utc=? "
                "WHERE decision_at_utc=2100",
                (manifest["holdout_end_at_utc"],))
        elif corruption == "decision_text":
            conn.execute(
                "UPDATE holdout_locked_decisions SET decision_at_utc='invalid' "
                "WHERE decision_at_utc=2100")
        elif corruption == "split_source":
            conn.execute(
                "UPDATE holdout_locked_rows SET source_sha256=? "
                "WHERE row_sha256=?",
                ("f" * 64, census[0]["row_sha256"]))
        else:
            conn.execute(
                "INSERT INTO holdout_locked_rows VALUES (?, ?, ?)",
                (_source_key(manifest["source"]), "f" * 64, "ghost"))
    expected = ("Orphaned" if corruption == "orphan_row" else
                "Split-source" if corruption == "split_source" else "Noncausal")
    second, other = _study(study="second", offset=100, decision_offset=5000)
    with pytest.raises(ValueError, match=expected):
        register_population_locked_holdout(path, second, other)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM holdout_claims WHERE study_id='second'"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM holdout_locked_rows WHERE study_id='one'"
        ).fetchone() == (35,)
        assert conn.execute(
            "SELECT count(*) FROM holdout_locked_decisions WHERE study_id='one'"
        ).fetchone() == (35,)
    clock[0] = manifest["holdout_end_at_utc"] + 1
    with pytest.raises(ValueError, match=expected):
        registry.claim_local_holdout_release(
            path, study_id="one",
            manifest_sha256=registration["manifest_sha256"])
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id='one'"
        ).fetchone() == (None,)


@pytest.mark.parametrize("corruption", [
    "balanced_row_replacement", "balanced_decision_replacement",
    "balanced_both_source_replacement",
])
def test_frozen_census_rechecked_atomically_before_outcome_loading(
        tmp_path, clock, corruption):
    """Balanced reservations can pass count/source-uniformity checks."""
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, outcomes, release_at = holdout_fixture()
    path = tmp_path / "frozen-population.sqlite"
    register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        if corruption == "balanced_row_replacement":
            conn.execute(
                "UPDATE holdout_locked_rows SET row_sha256=? WHERE row_sha256=?",
                ("f" * 64, census[0]["row_sha256"]))
        elif corruption == "balanced_decision_replacement":
            conn.execute(
                "UPDATE holdout_locked_decisions SET decision_at_utc=? "
                "WHERE decision_at_utc=?", (2101, 2100))
        else:
            # Change BOTH reservation tables to one different feed key.
            # Counts, decision windows and one-source checks still pass.
            conn.execute("UPDATE holdout_locked_rows SET source_sha256=?",
                         ("f" * 64,))
            conn.execute("UPDATE holdout_locked_decisions SET source_sha256=?",
                         ("f" * 64,))
    clock[0] = release_at
    loaded = []
    def load_outcomes():
        loaded.append(True)
        return outcomes
    with pytest.raises(ValueError, match=(
            "Frozen holdout population reservations differ|"
            "Inconsistent paired population reservations at release")):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, anchor, load_outcomes)
    assert loaded == []
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims "
            "WHERE study_id=?", (manifest["study_id"],)).fetchone() == (None,)


def test_exact_frozen_population_release_matches_and_remains_one_attempt(
        tmp_path, clock):
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, outcomes, release_at = holdout_fixture()
    path = tmp_path / "frozen-population-ok.sqlite"
    register_population_locked_holdout(path, manifest, census)
    clock[0] = release_at
    result = registry.audit_declared_holdout_release_once(
        path, manifest, census, anchor, lambda: outcomes)
    assert result["local_release_claim"]["local_frozen_population_matched"] is True
    assert result["declared_audit"]["profitable_edge_verified"] is False
    with pytest.raises(ValueError, match="already claimed"):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, anchor, lambda: outcomes)


def test_legacy_direct_claim_does_not_pretend_population_was_checked(
        tmp_path, clock):
    path = tmp_path / "legacy-no-population.sqlite"
    registry.register_local_holdout(
        path, study_id="legacy", manifest_sha256="a" * 64,
        holdout_start_at_utc=2000, holdout_end_at_utc=20000)
    clock[0] = 20001
    result = registry.claim_local_holdout_release(
        path, study_id="legacy", manifest_sha256="a" * 64)
    assert result["local_frozen_population_matched"] is False


def test_registration_rechecks_clock_before_commit(tmp_path, clock, monkeypatch):
    path = tmp_path / "late-population.sqlite"
    manifest, census = _study()
    ticks = iter((1251, 2000))  # Census insertion finishes at holdout start.
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: next(ticks))
    with pytest.raises(ValueError, match="reached holdout start"):
        register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='holdout_claims'"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='holdout_locked_rows'"
        ).fetchone() == (0,)


def test_registration_persists_final_transaction_clock(tmp_path, clock, monkeypatch):
    path = tmp_path / "committed-population.sqlite"
    manifest, census = _study()
    ticks = iter((1251, 1252))
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: next(ticks))
    result = register_population_locked_holdout(path, manifest, census)
    assert result["registered_at_utc"] == 1252
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT registered_at_utc FROM holdout_claims WHERE study_id='one'"
        ).fetchone() == (1252,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_rows").fetchone() == (35,)


def test_frozen_release_rejects_swapped_row_decision_pairing(tmp_path, clock):
    """Equal row and time sets must not conceal a changed row/time association."""
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, outcomes, release_at = holdout_fixture()
    path = tmp_path / "swapped-pair.sqlite"
    registration = register_population_locked_holdout(path, manifest, census)
    assert registration["locked_pair_count"] == len(census)
    with sqlite3.connect(path) as conn:
        # Use a temporary unused timestamp to satisfy the UNIQUE constraint.
        conn.execute("UPDATE holdout_locked_pairs SET decision_at_utc=9999 "
                     "WHERE decision_at_utc=2100")
        conn.execute("UPDATE holdout_locked_pairs SET decision_at_utc=2100 "
                     "WHERE decision_at_utc=2200")
        conn.execute("UPDATE holdout_locked_pairs SET decision_at_utc=2200 "
                     "WHERE decision_at_utc=9999")
        assert conn.execute("SELECT count(*) FROM holdout_locked_pairs").fetchone() == (35,)
    clock[0] = release_at
    loaded = []
    def load_outcomes():
        loaded.append(True)
        return outcomes
    with pytest.raises(ValueError, match="Frozen holdout population reservations differ"):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, anchor, load_outcomes)
    assert loaded == []
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id=?",
            (manifest["study_id"],)).fetchone() == (None,)


def test_missing_pair_reservation_blocks_registration_and_release(tmp_path, clock):
    path = tmp_path / "missing-pair.sqlite"
    manifest, census = _study()
    registration = register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM holdout_locked_pairs WHERE decision_at_utc=2100")
    second, other = _study(study="second", offset=100, decision_offset=5000)
    with pytest.raises(ValueError, match="Incomplete paired population"):
        register_population_locked_holdout(path, second, other)
    clock[0] = manifest["holdout_end_at_utc"] + 1
    with pytest.raises(ValueError, match="Incomplete paired population"):
        registry.claim_local_holdout_release(
            path, study_id="one", manifest_sha256=registration["manifest_sha256"])
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id='one'"
        ).fetchone() == (None,)
        assert conn.execute(
            "SELECT count(*) FROM holdout_claims WHERE study_id='second'"
        ).fetchone() == (0,)


def test_pre_pair_registry_not_silently_upgraded(tmp_path, clock):
    path = tmp_path / "old-pairless.sqlite"
    manifest, census = _study()
    registration = register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE holdout_locked_pairs")
    second, other = _study(study="second", offset=100, decision_offset=5000)
    with pytest.raises(ValueError, match="lacks paired reservations"):
        register_population_locked_holdout(path, second, other)
    clock[0] = manifest["holdout_end_at_utc"] + 1
    with pytest.raises(ValueError, match="Incomplete population-lock tables"):
        registry.claim_local_holdout_release(
            path, study_id="one", manifest_sha256=registration["manifest_sha256"])
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='holdout_locked_pairs'"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id='one'"
        ).fetchone() == (None,)


@pytest.mark.parametrize("shadow_name", [
    "holdout_claims", "holdout_locked_rows",
    "holdout_locked_decisions", "holdout_locked_pairs",
])
def test_registration_rejects_reserved_view_with_silent_insert_trigger(
        tmp_path, clock, shadow_name):
    """A view/INSTEAD OF trigger must never swallow a frozen reservation."""
    path = tmp_path / "shadowed-registration.sqlite"
    columns = {
        "holdout_claims": (
            "'' AS study_id, '' AS manifest_sha256, "
            "0 AS holdout_start_at_utc, 0 AS holdout_end_at_utc, "
            "0 AS registered_at_utc, NULL AS release_claimed_at_utc"
        ),
        "holdout_locked_rows": (
            "'' AS source_sha256, '' AS row_sha256, '' AS study_id"
        ),
        "holdout_locked_decisions": (
            "'' AS source_sha256, 0 AS decision_at_utc, '' AS study_id"
        ),
        "holdout_locked_pairs": (
            "'' AS source_sha256, '' AS row_sha256, "
            "0 AS decision_at_utc, '' AS study_id"
        ),
    }
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"CREATE VIEW {shadow_name} AS SELECT {columns[shadow_name]} WHERE 0"
        )
        conn.execute(
            f"CREATE TRIGGER shadow_insert INSTEAD OF INSERT ON {shadow_name} "
            "BEGIN SELECT 1; END"
        )
    manifest, census = _study()
    with pytest.raises(ValueError, match="Invalid population-lock schema object"):
        register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (shadow_name,)
        ).fetchone() == ("view",)
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND name IN ('holdout_claims', 'holdout_locked_rows', "
            "'holdout_locked_decisions', 'holdout_locked_pairs')"
        ).fetchone() == (0,)


@pytest.mark.parametrize("protected_table", [
    "holdout_claims", "holdout_locked_rows",
    "holdout_locked_decisions", "holdout_locked_pairs",
])
def test_registration_rejects_real_table_trigger_that_discards_inserts(
        tmp_path, clock, protected_table):
    """AFTER INSERT triggers can silently erase claims or reservations."""
    from app.local_holdout_population_lock import _DECISION_SCHEMA, _PAIR_SCHEMA

    path = tmp_path / "triggered-registration.sqlite"
    with sqlite3.connect(path) as conn:
        for schema in (registry._SCHEMA, _ROW_SCHEMA, _DECISION_SCHEMA, _PAIR_SCHEMA):
            conn.execute(schema)
        conn.execute(
            f"CREATE TRIGGER discard_insert AFTER INSERT ON {protected_table} "
            f"BEGIN DELETE FROM {protected_table}; END"
        )
    manifest, census = _study()
    with pytest.raises(ValueError, match="Invalid population-lock trigger"):
        register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='trigger' "
            "AND name='discard_insert'"
        ).fetchone() == (protected_table,)
        for table in (
            "holdout_claims", "holdout_locked_rows",
            "holdout_locked_decisions", "holdout_locked_pairs",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


@pytest.mark.parametrize("protected_table", [
    "holdout_claims", "holdout_locked_rows",
    "holdout_locked_decisions", "holdout_locked_pairs",
])
def test_release_rejects_triggers_added_after_population_registration(
        tmp_path, clock, protected_table):
    """A trigger added after registration must not bypass the release fence."""
    path = tmp_path / "triggered-release.sqlite"
    manifest, census = _study()
    registration = register_population_locked_holdout(path, manifest, census)
    with sqlite3.connect(path) as conn:
        if protected_table == "holdout_claims":
            # SQLite reports UPDATE rowcount=1 even if this trigger clears
            # the claimed timestamp; without a guard, a second claim works.
            conn.execute(
                "CREATE TRIGGER clear_release AFTER UPDATE OF "
                "release_claimed_at_utc ON holdout_claims "
                "BEGIN UPDATE holdout_claims SET release_claimed_at_utc=NULL "
                "WHERE study_id=NEW.study_id; END"
            )
        else:
            conn.execute(
                f"CREATE TRIGGER unexpected_release_trigger AFTER DELETE "
                f"ON {protected_table} BEGIN SELECT 1; END"
            )
    clock[0] = manifest["holdout_end_at_utc"] + 1
    with pytest.raises(ValueError, match="Invalid holdout registry trigger at release"):
        registry.claim_local_holdout_release(
            path, study_id=manifest["study_id"],
            manifest_sha256=registration["manifest_sha256"],
            expected_population_rows=[
                (row["row_sha256"], row["decision_at_utc"]) for row in census
            ],
            expected_source_key_sha256=_source_key(manifest["source"]),
        )
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id=?",
            (manifest["study_id"],)
        ).fetchone() == (None,)
        assert conn.execute(
            "SELECT count(*) FROM holdout_locked_pairs"
        ).fetchone() == (len(census),)


@pytest.mark.parametrize("shadow_name", [
    "holdout_claims", "holdout_locked_rows",
    "holdout_locked_decisions", "holdout_locked_pairs",
])
def test_case_variant_view_cannot_shadow_population_registration(
        tmp_path, clock, shadow_name):
    """SQLite names are case-insensitive; sqlite_master.name comparisons are not."""
    path = tmp_path / "mixed-case-registration.sqlite"
    columns = {
        "holdout_claims": (
            "'' AS study_id, '' AS manifest_sha256, "
            "0 AS holdout_start_at_utc, 0 AS holdout_end_at_utc, "
            "0 AS registered_at_utc, NULL AS release_claimed_at_utc"
        ),
        "holdout_locked_rows": (
            "'' AS source_sha256, '' AS row_sha256, '' AS study_id"
        ),
        "holdout_locked_decisions": (
            "'' AS source_sha256, 0 AS decision_at_utc, '' AS study_id"
        ),
        "holdout_locked_pairs": (
            "'' AS source_sha256, '' AS row_sha256, "
            "0 AS decision_at_utc, '' AS study_id"
        ),
    }
    upper = shadow_name.upper()
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE VIEW {upper} AS SELECT {columns[shadow_name]} WHERE 0")
        conn.execute(
            f"CREATE TRIGGER swallow_insert INSTEAD OF INSERT ON {upper} "
            "BEGIN SELECT 1; END"
        )
    with pytest.raises(ValueError, match="Invalid population-lock schema object"):
        register_population_locked_holdout(path, *_study())
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT name, type FROM sqlite_master WHERE lower(name)=?",
            (shadow_name,),
        ).fetchone() == (upper, "view")
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND lower(name) IN ('holdout_claims', 'holdout_locked_rows', "
            "'holdout_locked_decisions', 'holdout_locked_pairs')"
        ).fetchone() == (0,)


@pytest.mark.parametrize("protected_table", [
    "holdout_claims", "holdout_locked_rows",
    "holdout_locked_decisions", "holdout_locked_pairs",
])
def test_case_variant_trigger_target_blocks_population_registration(
        tmp_path, clock, protected_table):
    """sqlite_master.tbl_name preserves the case used by CREATE TRIGGER."""
    from app.local_holdout_population_lock import _DECISION_SCHEMA, _PAIR_SCHEMA

    path = tmp_path / "mixed-case-trigger.sqlite"
    with sqlite3.connect(path) as conn:
        for schema in (registry._SCHEMA, _ROW_SCHEMA, _DECISION_SCHEMA, _PAIR_SCHEMA):
            conn.execute(schema)
        conn.execute(
            f"CREATE TRIGGER silent_insert AFTER INSERT ON {protected_table.upper()} "
            f"BEGIN DELETE FROM {protected_table}; END"
        )
        assert conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='trigger'"
        ).fetchone() == (protected_table.upper(),)
    with pytest.raises(ValueError, match="Invalid population-lock trigger"):
        register_population_locked_holdout(path, *_study())
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM holdout_claims").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM holdout_locked_pairs").fetchone() == (0,)
