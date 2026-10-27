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
    def fail(*args):
        raise ValueError("bad outcomes")
    fake.audit_declared_holdout_release = fail
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)
    with pytest.raises(ValueError, match="bad outcomes"):
        registry.audit_declared_holdout_release_once(
            path, {"study_id": "study-1"}, [], {}, lambda: [])
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
    fake.audit_declared_holdout_release = lambda *args: {"status": "synthetic"}
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)
    def loader():
        with pytest.raises(ValueError, match="already claimed"):
            _claim(path)
        return []
    result = registry.audit_declared_holdout_release_once(
        path, {"study_id": "study-1"}, [], {}, loader)
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
    monkeypatch.setitem(sys.modules, "app.declared_holdout_release_gate", fake)
    with pytest.raises(ValueError, match="callable"):
        registry.audit_declared_holdout_release_once(
            path, {"study_id": "study-1"}, [], {}, [])
    assert _claim(path)["release_claimed_at_utc"] == 301


def test_real_declared_gate_integration_with_local_one_attempt(tmp_path, clock):
    # The real gate remains declared-only; this only proves the wrapper's
    # ordering and matching manifest digest with a synthetic holdout.
    from app.declared_holdout_release_gate import prepare_declared_holdout_manifest_sha256
    from test_declared_holdout_release_gate import fixture as holdout_fixture

    manifest, census, anchor, outcomes, _ = holdout_fixture()
    path = tmp_path / "integration.sqlite"
    clock[0] = 1251
    registry.register_local_holdout(
        path, study_id=manifest["study_id"],
        manifest_sha256=prepare_declared_holdout_manifest_sha256(manifest),
        holdout_start_at_utc=manifest["holdout_start_at_utc"],
        holdout_end_at_utc=manifest["holdout_end_at_utc"])
    clock[0] = manifest["holdout_end_at_utc"] + 1
    result = registry.audit_declared_holdout_release_once(
        path, manifest, census, anchor, lambda: outcomes)
    assert result["declared_audit"]["net_cash"] == "195.0000"
    assert result["declared_audit"]["profitable_edge_verified"] is False
    assert result["local_release_claim"]["release_claimed_at_utc"] == clock[0]
    with pytest.raises(ValueError, match="already claimed"):
        registry.audit_declared_holdout_release_once(
            path, manifest, census, anchor, lambda: outcomes)
