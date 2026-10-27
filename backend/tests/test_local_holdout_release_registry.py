"""Invented-clock, local SQLite only. No market data or brokerage calls."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from app import local_holdout_release_registry as registry


@pytest.fixture
def clock(monkeypatch):
    value = [100]
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: value[0])
    return value


def _register(path):
    return registry.register_local_holdout(
        path, study_id="study-1", manifest_sha256="a" * 64,
        holdout_start_at_utc=200, holdout_end_at_utc=300)


def _claim(path):
    return registry.claim_local_holdout_release(
        path, study_id="study-1", manifest_sha256="a" * 64)


def test_register_and_claim_exactly_once(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    assert _register(path)["registered_at_utc"] == 100
    clock[0] = 300
    assert _claim(path)["release_claimed_at_utc"] == 300
    with pytest.raises(ValueError, match="already claimed"):
        _claim(path)


def test_cannot_register_same_study_again_even_with_same_digest(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    with pytest.raises(sqlite3.IntegrityError):
        _register(path)


def test_cannot_register_after_start(tmp_path, clock):
    clock[0] = 200
    with pytest.raises(ValueError, match="precede"):
        _register(tmp_path / "holdout.sqlite")


def test_cannot_claim_before_end_or_missing_registry(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        _claim(path)
    _register(path)
    clock[0] = 299
    with pytest.raises(ValueError, match="not complete"):
        _claim(path)
    clock[0] = 300
    assert _claim(path)["local_one_attempt_claim_recorded"] is True


def test_wrong_study_or_digest_does_not_consume_claim(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 400
    with pytest.raises(ValueError, match="not registered"):
        registry.claim_local_holdout_release(path, study_id="other", manifest_sha256="a" * 64)
    with pytest.raises(ValueError, match="not registered"):
        registry.claim_local_holdout_release(path, study_id="study-1", manifest_sha256="b" * 64)
    assert _claim(path)["release_claimed_at_utc"] == 400


def test_clock_rollback_does_not_consume_claim(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 99
    with pytest.raises(ValueError, match="not complete|backwards"):
        _claim(path)
    clock[0] = 301
    assert _claim(path)["release_claimed_at_utc"] == 301


def test_concurrent_claims_exactly_one_wins(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 350
    def attempt(_):
        try:
            return _claim(path)["local_one_attempt_claim_recorded"]
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(24)))
    assert results.count(True) == 1
    assert results.count(False) == 23


@pytest.mark.parametrize("study,digest", [
    ("", "a" * 64), ("invalid space", "a" * 64), ("s", "A" * 64),
    ("s", "bad"), (True, "a" * 64), ("s", None)])
def test_invalid_identity_or_digest(tmp_path, clock, study, digest):
    with pytest.raises(ValueError):
        registry.register_local_holdout(
            tmp_path / "holdout.sqlite", study_id=study,
            manifest_sha256=digest, holdout_start_at_utc=200,
            holdout_end_at_utc=300)


@pytest.mark.parametrize("start,end", [
    (200, 200), (201, 200), (True, 300), (200, False),
    (-1, 300), (200, 8_640_000_001)])
def test_invalid_interval(tmp_path, clock, start, end):
    with pytest.raises(ValueError):
        registry.register_local_holdout(
            tmp_path / "holdout.sqlite", study_id="study-1",
            manifest_sha256="a" * 64,
            holdout_start_at_utc=start, holdout_end_at_utc=end)


def test_sqlite_claim_persists_across_connections(tmp_path, clock):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 301
    _claim(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT release_claimed_at_utc FROM holdout_claims").fetchone()
    assert row == (301,)
    with pytest.raises(ValueError, match="already claimed"):
        _claim(path)


def test_wrapper_burns_claim_before_invalid_evaluation(tmp_path, clock, monkeypatch):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 301
    # No need to construct outcomes: prove the claim is consumed even when
    # the later evaluation raises, using an import-compatible isolated stub.
    import sys
    import types
    fake = types.ModuleType("app.declared_holdout_release_gate")
    fake.prepare_declared_holdout_manifest_sha256 = lambda manifest: "a" * 64
    fake._validate_census = lambda manifest, census: None
    fake._validate_anchor = lambda manifest, anchor, digest: None
    def fail(*args):
        raise ValueError("bad outcomes")
    fake.audit_declared_holdout_release = fail
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)
    with pytest.raises(ValueError, match="bad outcomes"):
        registry.audit_declared_holdout_release_once(
            path, {"study_id": "study-1", "holdout_start_at_utc": 200,
                   "holdout_end_at_utc": 300}, [], {}, lambda: [])
    with pytest.raises(ValueError, match="already claimed"):
        _claim(path)


def test_loader_runs_only_after_durable_claim(tmp_path, clock, monkeypatch):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 301
    import sys
    import types
    fake = types.ModuleType("app.declared_holdout_release_gate")
    fake.prepare_declared_holdout_manifest_sha256 = lambda manifest: "a" * 64
    fake._validate_census = lambda manifest, census: None
    fake._validate_anchor = lambda manifest, anchor, digest: None
    fake.audit_declared_holdout_release = lambda *args: {"status": "synthetic"}
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)
    def loader():
        with pytest.raises(ValueError, match="already claimed"):
            _claim(path)
        return []
    result = registry.audit_declared_holdout_release_once(
        path, {"study_id": "study-1", "holdout_start_at_utc": 200,
                   "holdout_end_at_utc": 300}, [], {}, loader)
    assert result["declared_audit"] == {"status": "synthetic"}
    assert result["local_release_claim"]["independently_trusted_registry"] is False


def test_noncallable_loader_does_not_consume_claim(tmp_path, clock, monkeypatch):
    path = tmp_path / "holdout.sqlite"
    _register(path)
    clock[0] = 301
    import sys
    import types
    fake = types.ModuleType("app.declared_holdout_release_gate")
    fake.prepare_declared_holdout_manifest_sha256 = lambda manifest: "a" * 64
    fake._validate_census = lambda manifest, census: None
    fake._validate_anchor = lambda manifest, anchor, digest: None
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)
    with pytest.raises(ValueError, match="callable"):
        registry.audit_declared_holdout_release_once(
            path, {"study_id": "study-1", "holdout_start_at_utc": 200,
                   "holdout_end_at_utc": 300}, [], {}, [])
    assert _claim(path)["release_claimed_at_utc"] == 301


def test_real_declared_gate_integration_with_local_one_attempt(tmp_path, clock):
    # The real gate remains declared-only; this only proves the wrapper's
    # ordering and matching manifest digest with a synthetic holdout.
    from app.local_holdout_population_lock import register_population_locked_holdout
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, outcomes, _ = holdout_fixture()
    path = tmp_path / "integration.sqlite"
    clock[0] = 1251
    register_population_locked_holdout(path, manifest, census)
    clock[0] = manifest["holdout_end_at_utc"] + 1
    result = registry.audit_declared_holdout_release_once(
        path, manifest, census, anchor, lambda: outcomes)
    assert result["declared_audit"]["net_cash"] == "195.0000"
    assert result["declared_audit"]["profitable_edge_verified"] is False
    assert result["local_release_claim"]["release_claimed_at_utc"] == clock[0]
    assert result["local_release_claim"]["local_frozen_population_matched"] is True
    with pytest.raises(ValueError, match="already claimed"):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, anchor, lambda: outcomes)


@pytest.mark.parametrize("column,replacement", [
    ("holdout_start_at_utc", 201),
    ("holdout_end_at_utc", 301),
])
def test_wrapper_rejects_modified_registered_interval_without_loading_outcomes(
        tmp_path, clock, monkeypatch, column, replacement):
    # The stored manifest digest remains correct, but a local database edit
    # changes one interval endpoint. The guarded wrapper must not consume a
    # release claim or load any outcome data.
    path = tmp_path / "interval.sqlite"
    _register(path)
    with sqlite3.connect(path) as conn:
        conn.execute(f"UPDATE holdout_claims SET {column}=?", (replacement,))
    clock[0] = 350
    import sys
    import types
    fake = types.ModuleType("app.declared_holdout_release_gate")
    fake.prepare_declared_holdout_manifest_sha256 = lambda manifest: "a" * 64
    fake._validate_census = lambda manifest, census: None
    fake._validate_anchor = lambda manifest, anchor, digest: None
    fake.audit_declared_holdout_release = lambda *args: pytest.fail(
        "Unexpected evaluation of a changed registered interval")
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)

    def unexpected_loader():
        pytest.fail("Outcomes loaded before registered interval check")

    with pytest.raises(ValueError, match="differs from frozen manifest"):
        registry.audit_declared_holdout_release_once(
            path, {"study_id": "study-1", "holdout_start_at_utc": 200,
                   "holdout_end_at_utc": 300}, [], {}, unexpected_loader)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims"
        ).fetchone() == (None,)


def test_expected_holdout_interval_arguments_fail_closed_before_claim(tmp_path, clock):
    path = tmp_path / "interval.sqlite"
    _register(path)
    clock[0] = 350
    for start, end in [(200, None), (None, 300), (True, 300),
                       (200, False), (300, 200)]:
        with pytest.raises(ValueError, match="Expected holdout interval|Invalid expected"):
            registry.claim_local_holdout_release(
                path, study_id="study-1", manifest_sha256="a" * 64,
                expected_holdout_start_at_utc=start,
                expected_holdout_end_at_utc=end)
    assert registry.claim_local_holdout_release(
        path, study_id="study-1", manifest_sha256="a" * 64,
        expected_holdout_start_at_utc=200,
        expected_holdout_end_at_utc=300)["release_claimed_at_utc"] == 350



def test_frozen_population_claim_rejects_legacy_unreserved_registry(tmp_path, clock):
    path = tmp_path / "legacy-frozen.sqlite"
    _register(path)
    clock[0] = 350
    with pytest.raises(ValueError, match="requires locked reservation tables"):
        registry.claim_local_holdout_release(
            path, study_id="study-1", manifest_sha256="a" * 64,
            expected_holdout_start_at_utc=200,
            expected_holdout_end_at_utc=300,
            expected_population_rows=[("b" * 64, 210)],
            expected_source_key_sha256="c" * 64)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims"
        ).fetchone() == (None,)
    # Explicit legacy direct callers can still claim without asserting
    # frozen-population verification; the result cannot claim a match.
    result = _claim(path)
    assert result["local_frozen_population_matched"] is False


def test_frozen_wrapper_never_loads_outcomes_from_legacy_registry(tmp_path, clock):
    from app.declared_holdout_release_gate import prepare_declared_holdout_manifest_sha256
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, _, _ = holdout_fixture()
    path = tmp_path / "legacy-wrapper.sqlite"
    clock[0] = 1251
    registry.register_local_holdout(
        path, study_id=manifest["study_id"],
        manifest_sha256=prepare_declared_holdout_manifest_sha256(manifest),
        holdout_start_at_utc=manifest["holdout_start_at_utc"],
        holdout_end_at_utc=manifest["holdout_end_at_utc"])
    clock[0] = manifest["holdout_end_at_utc"] + 1

    def forbidden_loader():
        pytest.fail("Outcome loader called without frozen population reservations")

    with pytest.raises(ValueError, match="requires locked reservation tables"):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, anchor, forbidden_loader)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims"
        ).fetchone() == (None,)


def test_registration_rechecks_clock_before_commit(tmp_path, clock, monkeypatch):
    path = tmp_path / "late-registration.sqlite"
    ticks = iter((100, 200))  # Lock wait or work crosses holdout start.
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: next(ticks))
    with pytest.raises(ValueError, match="reached holdout start"):
        _register(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='holdout_claims'"
        ).fetchone() == (0,)


def test_registration_uses_final_transaction_clock(tmp_path, clock, monkeypatch):
    path = tmp_path / "committed-registration.sqlite"
    ticks = iter((100, 101))
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: next(ticks))
    assert _register(path)["registered_at_utc"] == 101
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT registered_at_utc FROM holdout_claims WHERE study_id='study-1'"
        ).fetchone() == (101,)


def test_release_rechecks_clock_before_consuming_claim(tmp_path, clock, monkeypatch):
    path = tmp_path / "clock-race.sqlite"
    _register(path)
    ticks = iter((301, 299))  # The local clock rolls back while awaiting the lock.
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: next(ticks))
    with pytest.raises(ValueError, match="clock moved backwards"):
        _claim(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims "
            "WHERE study_id='study-1'"
        ).fetchone() == (None,)
    monkeypatch.setattr(registry, "_now_utc_seconds", lambda: 302)
    assert _claim(path)["release_claimed_at_utc"] == 302


@pytest.mark.parametrize("corruption", ["reordered", "changed_row", "missing_row", "wrong_source"])
def test_guarded_wrapper_validates_frozen_census_before_legacy_claim_or_outcomes(
        tmp_path, clock, corruption):
    # A legacy registry has no row reservations. Even there, malformed
    # census declarations must not open the outcome loader and must leave
    # the local one-attempt release unconsumed.
    from app.declared_holdout_release_gate import prepare_declared_holdout_manifest_sha256
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, _, _ = holdout_fixture()
    path = tmp_path / "legacy-preflight.sqlite"
    clock[0] = manifest["registered_at_utc"] + 1
    registry.register_local_holdout(
        path, study_id=manifest["study_id"],
        manifest_sha256=prepare_declared_holdout_manifest_sha256(manifest),
        holdout_start_at_utc=manifest["holdout_start_at_utc"],
        holdout_end_at_utc=manifest["holdout_end_at_utc"])
    changed = [dict(row) for row in census]
    if corruption == "reordered":
        changed.reverse()
    elif corruption == "changed_row":
        original = changed[0]["row_sha256"]
        changed[0]["row_sha256"] = "f" * 64 if original != "f" * 64 else "e" * 64
    elif corruption == "missing_row":
        changed.pop()
    else:
        changed[0]["source_sha256"] = "f" * 64 if (
            changed[0]["source_sha256"] != "f" * 64) else "e" * 64
    clock[0] = manifest["holdout_end_at_utc"] + 1
    calls = []
    def forbidden_loader():
        calls.append(True)
        pytest.fail("Invalid frozen census reached outcome loader")

    with pytest.raises(ValueError):
        registry.audit_declared_holdout_release_once(
            path, manifest, changed, anchor, forbidden_loader)
    assert calls == []
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims "
            "WHERE study_id=?", (manifest["study_id"],)).fetchone() == (None,)


@pytest.mark.parametrize("corruption", [
    "missing_field", "wrong_manifest", "late_anchor", "early_anchor",
    "invalid_receipt", "invalid_reference",
])
def test_declared_anchor_preflight_rejects_before_claim_and_outcome_loading(
        tmp_path, clock, corruption):
    """Bad anchor declarations must not burn the sole holdout release."""
    from app.local_holdout_population_lock import register_population_locked_holdout
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, outcomes, _ = holdout_fixture()
    path = tmp_path / "anchor-preflight.sqlite"
    clock[0] = manifest["registered_at_utc"] + 1
    register_population_locked_holdout(path, manifest, census)
    clock[0] = manifest["holdout_end_at_utc"] + 1
    bad_anchor = dict(anchor)
    if corruption == "missing_field":
        del bad_anchor["external_record_sha256"]
    elif corruption == "wrong_manifest":
        bad_anchor["manifest_sha256"] = "f" * 64
    elif corruption == "late_anchor":
        bad_anchor["anchored_at_utc"] = manifest["holdout_start_at_utc"]
    elif corruption == "early_anchor":
        bad_anchor["anchored_at_utc"] = manifest["registered_at_utc"] - 1
    elif corruption == "invalid_receipt":
        bad_anchor["external_record_sha256"] = "not-a-digest"
    else:
        bad_anchor["anchor_reference"] = ""

    calls = []
    def forbidden_loader():
        calls.append(True)
        pytest.fail("Invalid anchor reached outcome loader")

    with pytest.raises(ValueError):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, bad_anchor, forbidden_loader)
    assert calls == []
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT release_claimed_at_utc FROM holdout_claims WHERE study_id=?",
            (manifest["study_id"],)).fetchone() == (None,)
    # A valid declaration can still use the original, unconsumed attempt.
    result = registry.audit_declared_holdout_release_once(
        path, manifest, census, anchor, lambda: outcomes)
    assert result["local_release_claim"]["local_one_attempt_claim_recorded"] is True
    assert result["local_release_claim"]["local_frozen_population_matched"] is True
