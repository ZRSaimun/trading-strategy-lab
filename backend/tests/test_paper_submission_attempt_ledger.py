"""Synthetic offline tests: no network, broker credentials or real orders."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from app import paper_submission_attempt_ledger as ledger
from app.paper_submission_attempt_ledger import (
    initialize_ledger, inspect_ledger, prepare_intent, mark_attempt_unknown,
    record_declared_reconciliation,
)

H = 'a' * 64
E = 'b' * 64
KEY = dict(broker='T212-INVEST-DEMO', account_alias='demo-account',
           client_order_id='order-1', intent_sha256=H)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / 'ledger.sqlite'
    initialize_ledger(p)
    return p


def prep(db, **kw):
    return prepare_intent(db, recorded_at_ms=100, **(KEY | kw))


def attempt(db, **kw):
    return mark_attempt_unknown(db, recorded_at_ms=101, **(KEY | kw))


def reconcile(db, outcome='FILLED', **kw):
    key = {k: v for k, v in KEY.items() if k != 'intent_sha256'}
    return record_declared_reconciliation(db, recorded_at_ms=102,
                                          evidence_sha256=E, outcome=outcome,
                                          **(key | kw))


def test_new_ledger_empty(db):
    x = inspect_ledger(db)
    assert x['event_count'] == 0 and x['order_count'] == 0
    assert x['last_recorded_at_ms'] is None
    assert x['may_submit_real_order'] is False


def test_lifecycle_and_no_execution(db):
    for x in (prep(db), attempt(db), reconcile(db)):
        assert x['may_submit_paper_order'] is False
        assert x['may_submit_real_order'] is False
    x = inspect_ledger(db)
    assert x['event_count'] == 3
    assert x['last_recorded_at_ms'] == 102
    assert x['orders'][0]['status'] == 'RECONCILED_FILLED'
    assert x['status'] == 'HOLD_RECONCILIATION'


@pytest.mark.parametrize('outcome', ['FILLED', 'REJECTED', 'CANCELLED'])
def test_terminal_outcomes_are_irreversible(db, outcome):
    prep(db); attempt(db); reconcile(db, outcome)
    with pytest.raises(ValueError):
        attempt(db)
    with pytest.raises(ValueError):
        reconcile(db, outcome)
    assert inspect_ledger(db)['event_count'] == 3


def test_duplicate_id_same_payload_rejected(db):
    prep(db)
    with pytest.raises(ValueError, match='Duplicate'):
        prep(db)
    assert inspect_ledger(db)['event_count'] == 1


def test_duplicate_id_different_payload_rejected(db):
    prep(db)
    with pytest.raises(ValueError, match='Duplicate'):
        prep(db, intent_sha256=E)


def test_same_intent_new_id_rejected(db):
    prep(db)
    with pytest.raises(sqlite3.IntegrityError):
        prep(db, client_order_id='order-2')
    assert inspect_ledger(db)['event_count'] == 1


def test_distinct_intent_new_id_accepted(db):
    prep(db)
    prep(db, client_order_id='order-2', intent_sha256=E)
    assert inspect_ledger(db)['order_count'] == 2


def test_restart_unknown_stays_unknown(db):
    prep(db); attempt(db)
    assert inspect_ledger(db)['orders'][0]['status'] == 'ATTEMPT_UNKNOWN'
    with pytest.raises(ValueError, match='retry forbidden'):
        attempt(db)


def test_attempt_before_prepare_rejected(db):
    with pytest.raises(ValueError):
        attempt(db)


def test_reconcile_before_attempt_rejected(db):
    prep(db)
    with pytest.raises(ValueError):
        reconcile(db)


def test_wrong_intent_fingerprint_cannot_mark_attempt(db):
    prep(db)
    with pytest.raises(ValueError):
        attempt(db, intent_sha256=E)


def test_parallel_claims_exactly_one_wins(db):
    prep(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, db) for _ in range(2)]
        results = []
        for f in futures:
            try:
                results.append(f.result())
            except ValueError:
                results.append(None)
    assert sum(x is not None for x in results) == 1
    assert inspect_ledger(db)['event_count'] == 2


def test_clock_regression_rejected(db):
    prep(db)
    with pytest.raises(ValueError, match='Clock regression'):
        mark_attempt_unknown(db, recorded_at_ms=99, **KEY)


@pytest.mark.parametrize('bad', [None, -1, 1.0, True, '100', 8_640_000_000_000_001])
def test_bad_clock_rejected(db, bad):
    with pytest.raises(ValueError):
        prepare_intent(db, recorded_at_ms=bad, **KEY)


@pytest.mark.parametrize('broker', ['Trading212-CFD', 'CFD', 'PAPER-LOCAL;DROP', ''])
def test_unsupported_broker_rejected(db, broker):
    with pytest.raises(ValueError):
        prep(db, broker=broker)


@pytest.mark.parametrize('fingerprint', ['A'*64, 'a'*63, 'a'*65, 'not-a-hash', None])
def test_bad_fingerprint_rejected(db, fingerprint):
    with pytest.raises(ValueError):
        prep(db, intent_sha256=fingerprint)


def test_unknown_outcome_rejected(db):
    prep(db); attempt(db)
    with pytest.raises(ValueError):
        reconcile(db, outcome='PARTIALLY_FILLED')


def test_tampered_projection_rejected(db):
    prep(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE intents SET status='RECONCILED_FILLED'")
    with pytest.raises(ValueError, match='projection'):
        inspect_ledger(db)
    with pytest.raises(ValueError, match='projection'):
        attempt(db)


def test_tampered_event_rejected(db):
    prep(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE events SET evidence_sha=?", (E,))
    with pytest.raises(ValueError, match='hash mismatch'):
        inspect_ledger(db)


def test_deleted_event_rejected(db):
    prep(db); attempt(db)
    with sqlite3.connect(db) as c:
        c.execute('DELETE FROM events WHERE seq=1')
    with pytest.raises(ValueError, match='sequence'):
        inspect_ledger(db)


def test_deleted_index_rejected(db):
    with sqlite3.connect(db) as c:
        c.execute('DROP INDEX unique_account_intent')
    with pytest.raises(ValueError, match='schema objects'):
        inspect_ledger(db)


@pytest.mark.parametrize('ddl', [
    'ALTER TABLE events ADD COLUMN ignored TEXT',
    'CREATE VIEW extra_audit AS SELECT * FROM events',
    'CREATE INDEX extra_event_index ON events (event)',
    'DROP INDEX unique_account_intent; CREATE INDEX unique_account_intent ON intents (broker, account, intent_sha)',
])
def test_ledger_rejects_unreviewed_schema_changes(db, ddl):
    prep(db)
    with sqlite3.connect(db) as c:
        c.executescript(ddl)
    with pytest.raises(ValueError, match='schema objects'):
        inspect_ledger(db)
    with pytest.raises(ValueError, match='schema objects'):
        attempt(db)


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_sqlite_statistics_table_is_unreviewed_schema(db, operation):
    """ANALYZE creates sqlite_stat1, previously hidden by sqlite_% filtering."""
    prep(db)
    with sqlite3.connect(db) as c:
        c.execute('ANALYZE')
        assert c.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='sqlite_stat1'"
        ).fetchone()[0] == 1
    with pytest.raises(ValueError, match='schema objects'):
        if operation == 'inspect':
            inspect_ledger(db)
        else:
            attempt(db)
    # Refusing the unreviewed schema must not append any order evidence.
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT count(*) FROM events').fetchone()[0] == 1


def test_schema_mismatch_rejected(db):
    with sqlite3.connect(db) as c:
        c.execute('PRAGMA user_version=9')
    with pytest.raises(ValueError, match='schema'):
        inspect_ledger(db)


def test_refuses_reinitialize(db):
    with pytest.raises(ValueError, match='exists'):
        initialize_ledger(db)
    assert inspect_ledger(db)['event_count'] == 0


def test_missing_file_does_not_autocreate(tmp_path):
    p = tmp_path / 'missing.sqlite'
    with pytest.raises(ValueError, match='Existing'):
        inspect_ledger(p)
    assert not p.exists()


def test_symlink_rejected(db, tmp_path):
    p = tmp_path / 'alias.sqlite'
    p.symlink_to(db)
    with pytest.raises(ValueError, match='Existing'):
        inspect_ledger(p)
    with pytest.raises(ValueError, match='exists'):
        initialize_ledger(p)


def test_different_accounts_are_isolated(db):
    prep(db)
    prep(db, account_alias='other-account')
    assert inspect_ledger(db)['order_count'] == 2


def test_audit_tip_changes_on_transition(db):
    a = inspect_ledger(db)['audit_tip_sha256']
    prep(db)
    b = inspect_ledger(db)['audit_tip_sha256']
    attempt(db)
    c = inspect_ledger(db)['audit_tip_sha256']
    assert len({a, b, c}) == 3


def test_disappeared_ledger_cannot_be_recreated_by_read_or_write(tmp_path, monkeypatch):
    """Simulate a stale is_file() preflight followed by a missing SQLite file."""
    p = tmp_path / 'removed-between-check-and-open.sqlite'
    original = ledger.Path.is_file

    def stale_preflight(path):
        return True if path == p else original(path)

    monkeypatch.setattr(ledger.Path, 'is_file', stale_preflight)
    with pytest.raises(ValueError, match='disappeared'):
        inspect_ledger(p)
    assert not p.exists()
    with pytest.raises(ValueError, match='disappeared'):
        prepare_intent(p, recorded_at_ms=100, **KEY)
    assert not p.exists()


def test_inspection_uses_read_only_uri_and_writes_require_existing_db(db, monkeypatch):
    calls = []
    real_connect = ledger.sqlite3.connect

    def traced_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ledger.sqlite3, 'connect', traced_connect)
    assert inspect_ledger(db)['event_count'] == 0
    assert calls[-1][1]['uri'] is True
    assert calls[-1][0][0].endswith('?mode=ro')
    prep(db)
    assert calls[-1][1]['uri'] is True
    assert calls[-1][0][0].endswith('?mode=rw')


def test_projection_capacity_rejected_before_unbounded_fetch(db, monkeypatch):
    monkeypatch.setattr(ledger, 'MAX_EVENTS', 2)
    with sqlite3.connect(db) as conn:
        for i in range(3):
            conn.execute('INSERT INTO intents VALUES (?,?,?,?,?)',
                         ('PAPER-LOCAL', 'test-account', f'order-{i}',
                          f'{i + 1:064x}', 'PREPARED'))
    with pytest.raises(ValueError, match='intent capacity'):
        inspect_ledger(db)
    with pytest.raises(ValueError, match='intent capacity'):
        prep(db)


def test_ledger_path_uri_escapes_reserved_characters(tmp_path):
    p = tmp_path / 'orders ? #.sqlite'
    initialize_ledger(p)
    assert inspect_ledger(p)['event_count'] == 0
    assert prepare_intent(p, recorded_at_ms=100, **KEY)['may_submit_real_order'] is False


def test_ledger_file_capacity_fails_closed_without_modification(db, monkeypatch):
    prep(db)
    before = db.read_bytes()
    monkeypatch.setattr(ledger, 'MAX_LEDGER_BYTES', 1)
    with pytest.raises(ValueError, match='byte capacity'):
        inspect_ledger(db)
    with pytest.raises(ValueError, match='byte capacity'):
        attempt(db)
    assert db.read_bytes() == before


def test_sqlite_decoded_value_limit_applied_to_read_and_write(db):
    for read_only in (True, False):
        conn = ledger._connect(db, read_only=read_only)
        try:
            assert conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == ledger.MAX_SQLITE_VALUE_BYTES
            with pytest.raises(sqlite3.DataError, match='too big'):
                conn.execute('SELECT ?', ('x' * (ledger.MAX_SQLITE_VALUE_BYTES + 1),)).fetchone()
        finally:
            conn.close()


def test_oversized_corrupt_audit_field_fails_closed(db):
    prep(db)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE events SET evidence_sha=?', ('x' * 5000,))
    with pytest.raises(sqlite3.DataError, match='too big'):
        inspect_ledger(db)
    with pytest.raises(sqlite3.DataError, match='too big'):
        attempt(db)


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
@pytest.mark.parametrize('replacement_kind', ['regular', 'symlink'])
def test_ledger_path_swap_during_sqlite_open_fails_closed(
        db, tmp_path, monkeypatch, operation, replacement_kind):
    """A changed inode or symlink after preflight must not receive writes."""
    other = tmp_path / 'replacement.sqlite'
    initialize_ledger(other)
    original = tmp_path / 'saved-original.sqlite'
    real_connect = ledger.sqlite3.connect
    swapped = False

    def swap_during_open(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            db.rename(original)
            if replacement_kind == 'regular':
                other.rename(db)
            else:
                db.symlink_to(other)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ledger.sqlite3, 'connect', swap_during_open)
    with pytest.raises(ValueError, match='identity changed'):
        if operation == 'inspect':
            inspect_ledger(db)
        else:
            prep(db)
    assert swapped
    # Restore the real connector before checking both untouched ledgers.
    monkeypatch.setattr(ledger.sqlite3, 'connect', real_connect)
    assert inspect_ledger(original)['event_count'] == 0
    assert inspect_ledger(db if replacement_kind == 'regular' else other)['event_count'] == 0


def test_initialize_creates_private_ledger_even_with_permissive_umask(tmp_path):
    import os
    p = tmp_path / 'private-ledger.sqlite'
    original_umask = os.umask(0)
    try:
        initialize_ledger(p)
    finally:
        os.umask(original_umask)
    assert p.stat().st_mode & 0o077 == 0
    assert inspect_ledger(p)['event_count'] == 0


def test_initialize_does_not_recreate_disappeared_exclusive_file(tmp_path, monkeypatch):
    p = tmp_path / 'disappearing-init.sqlite'
    real_connect = ledger._connect

    def disappear_before_sqlite_open(path, **kwargs):
        if path == p:
            p.unlink()
        return real_connect(path, **kwargs)

    monkeypatch.setattr(ledger, '_connect', disappear_before_sqlite_open)
    with pytest.raises(ValueError, match='Existing regular ledger file required'):
        initialize_ledger(p)
    assert not p.exists()


@pytest.mark.parametrize('replacement_kind', ['regular', 'symlink'])
def test_initialize_rejects_replacement_after_exclusive_create(
        tmp_path, monkeypatch, replacement_kind):
    p = tmp_path / 'new-ledger.sqlite'
    other = tmp_path / 'other-ledger.sqlite'
    saved = tmp_path / 'saved-new-ledger.sqlite'
    initialize_ledger(other)
    real_connect = ledger._connect
    replaced = False

    def swap_before_sqlite_open(path, **kwargs):
        nonlocal replaced
        if path == p and not replaced:
            replaced = True
            p.rename(saved)
            if replacement_kind == 'regular':
                other.rename(p)
            else:
                p.symlink_to(other)
        return real_connect(path, **kwargs)

    monkeypatch.setattr(ledger, '_connect', swap_before_sqlite_open)
    with pytest.raises(ValueError, match='identity changed|Existing regular ledger'):
        initialize_ledger(p)
    assert replaced
    monkeypatch.setattr(ledger, '_connect', real_connect)
    assert saved.stat().st_size == 0
    assert inspect_ledger(p if replacement_kind == 'regular' else other)['event_count'] == 0


@pytest.mark.parametrize('mode', [0o644, 0o666, 0o400, 0o700])
@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_ledger_rejects_nonprivate_file_modes(db, mode, operation):
    original = db.read_bytes()
    db.chmod(mode)
    try:
        with pytest.raises(ValueError, match='private mode 0600'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert db.read_bytes() == original
    finally:
        db.chmod(0o600)
    assert inspect_ledger(db)['event_count'] == 0


def test_ledger_rejects_hardlinked_storage(db, tmp_path):
    import os
    second_name = tmp_path / 'second-ledger-name.sqlite'
    os.link(db, second_name)
    try:
        with pytest.raises(ValueError, match='hardlinks'):
            inspect_ledger(db)
        with pytest.raises(ValueError, match='hardlinks'):
            prep(db)
    finally:
        second_name.unlink()
    assert inspect_ledger(db)['event_count'] == 0


def test_initialize_rejects_public_parent_before_creating_file(tmp_path):
    parent = tmp_path / 'public'
    parent.mkdir(mode=0o700)
    parent.chmod(0o777)
    try:
        db = parent / 'ledger.sqlite'
        with pytest.raises(ValueError, match='private directory'):
            initialize_ledger(db)
        assert not db.exists()
    finally:
        parent.chmod(0o700)


def test_existing_ledger_rejects_relaxed_parent_permissions(tmp_path):
    parent = tmp_path / 'private'
    parent.mkdir(mode=0o700)
    db = parent / 'ledger.sqlite'
    initialize_ledger(db)
    parent.chmod(0o755)
    try:
        with pytest.raises(ValueError, match='private directory'):
            inspect_ledger(db)
        with pytest.raises(ValueError, match='private directory'):
            prepare_intent(db, recorded_at_ms=100, **KEY)
    finally:
        parent.chmod(0o700)
    assert inspect_ledger(db)['event_count'] == 0


def test_initialize_rejects_symlinked_parent(tmp_path):
    actual = tmp_path / 'actual'
    actual.mkdir(mode=0o700)
    alias = tmp_path / 'alias'
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        initialize_ledger(alias / 'ledger.sqlite')
    assert not (actual / 'ledger.sqlite').exists()


def test_ledger_parent_swap_during_open_fails_closed(tmp_path, monkeypatch):
    active = tmp_path / 'active'
    active.mkdir(mode=0o700)
    db = active / 'ledger.sqlite'
    initialize_ledger(db)
    other = tmp_path / 'other'
    other.mkdir(mode=0o700)
    initialize_ledger(other / 'ledger.sqlite')
    saved = tmp_path / 'saved'
    real_connect = ledger.sqlite3.connect
    swapped = False

    def swap_parent_during_open(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            active.rename(saved)
            other.rename(active)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ledger.sqlite3, 'connect', swap_parent_during_open)
    with pytest.raises(ValueError, match='parent identity changed'):
        inspect_ledger(db)
    assert swapped
    monkeypatch.setattr(ledger.sqlite3, 'connect', real_connect)
    assert inspect_ledger(saved / 'ledger.sqlite')['event_count'] == 0
    assert inspect_ledger(db)['event_count'] == 0


def test_unknown_commit_survives_abrupt_process_exit(db):
    """A committed UNKNOWN must survive an actual process death, not just restart."""
    import os
    import subprocess
    import sys
    prep(db)
    script = (
        "import os, sys; "
        "from app.paper_submission_attempt_ledger import mark_attempt_unknown; "
        "mark_attempt_unknown(sys.argv[1], broker='T212-INVEST-DEMO', "
        "account_alias='demo-account', client_order_id='order-1', "
        "intent_sha256='a'*64, recorded_at_ms=101); os._exit(37)"
    )
    env = os.environ.copy()
    backend_dir = str(ledger.Path(ledger.__file__).resolve().parents[1])
    env['PYTHONPATH'] = backend_dir + os.pathsep + env.get('PYTHONPATH', '')
    child = subprocess.run([sys.executable, '-c', script, str(db)],
                           env=env, timeout=15, check=False)
    assert child.returncode == 37
    assert inspect_ledger(db)['orders'][0]['status'] == 'ATTEMPT_UNKNOWN'
    with pytest.raises(ValueError, match='retry forbidden'):
        attempt(db)


def test_uncommitted_sqlite_transition_rolls_back_after_process_death(db):
    """Abrupt exit inside an IMMEDIATE transaction must not persist partial state."""
    import os
    import subprocess
    import sys
    prep(db)
    script = (
        "import os, sys; "
        "from app.paper_submission_attempt_ledger import _connect; "
        "conn=_connect(sys.argv[1]); conn.execute('PRAGMA synchronous=FULL'); "
        "conn.execute('BEGIN IMMEDIATE'); "
        "conn.execute(\"UPDATE intents SET status='ATTEMPT_UNKNOWN'\"); "
        "os._exit(41)"
    )
    env = os.environ.copy()
    backend_dir = str(ledger.Path(ledger.__file__).resolve().parents[1])
    env['PYTHONPATH'] = backend_dir + os.pathsep + env.get('PYTHONPATH', '')
    child = subprocess.run([sys.executable, '-c', script, str(db)],
                           env=env, timeout=15, check=False)
    assert child.returncode == 41
    snapshot = inspect_ledger(db)
    assert snapshot['event_count'] == 1
    assert snapshot['orders'][0]['status'] == 'PREPARED'
    assert attempt(db)['status'] == 'ATTEMPT_UNKNOWN'


@pytest.mark.parametrize('suffix', ['-wal', '-shm'])
@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_unreviewed_sqlite_sidecars_quarantine_read_and_write(db, suffix, operation):
    prep(db)
    before = db.read_bytes()
    sidecar = ledger.Path(str(db) + suffix)
    sidecar.write_bytes(b'untrusted-sidecar')
    try:
        with pytest.raises(ValueError, match='WAL/SHM sidecar'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                attempt(db)
        assert db.read_bytes() == before
    finally:
        sidecar.unlink()
    assert inspect_ledger(db)['event_count'] == 1


def test_dangling_wal_sidecar_symlink_fails_closed(db):
    sidecar = ledger.Path(str(db) + '-wal')
    sidecar.symlink_to(db.parent / 'does-not-exist')
    try:
        with pytest.raises(ValueError, match='WAL/SHM sidecar'):
            inspect_ledger(db)
    finally:
        sidecar.unlink()
    assert inspect_ledger(db)['event_count'] == 0


def test_initialization_refuses_orphan_sqlite_sidecar(tmp_path):
    db = tmp_path / 'orphan-ledger.sqlite'
    sidecar = ledger.Path(str(db) + '-wal')
    sidecar.write_bytes(b'orphaned')
    with pytest.raises(ValueError, match='WAL/SHM sidecar'):
        initialize_ledger(db)
    assert not db.exists()
    assert sidecar.read_bytes() == b'orphaned'


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_wal_mode_in_sqlite_header_is_not_silently_repaired(db, operation):
    conn = sqlite3.connect(db)
    try:
        assert conn.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    finally:
        conn.close()
    # SQLite normally cleans its WAL sidecars on clean close, but the
    # persisted journal mode still must be rejected without conversion.
    with pytest.raises(ValueError, match='WAL/SHM sidecar|journal mode'):
        if operation == 'inspect':
            inspect_ledger(db)
        else:
            prep(db)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute('PRAGMA journal_mode').fetchone() == ('wal',)
    finally:
        conn.close()


@pytest.mark.parametrize('kind', ['symlink', 'directory', 'hardlink', 'oversize'])
@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_unsafe_rollback_journal_quarantines_without_touching_target(
        db, tmp_path, kind, operation):
    """A journal is writable SQLite state; reject unsafe path types before open."""
    import os
    journal = ledger.Path(str(db) + '-journal')
    target = tmp_path / 'protected'
    target.write_bytes(b'protected-data')
    original = db.read_bytes()
    if kind == 'symlink':
        journal.symlink_to(target)
    elif kind == 'directory':
        journal.mkdir()
    elif kind == 'hardlink':
        os.link(target, journal)
    else:
        with journal.open('wb') as handle:
            handle.truncate(ledger.MAX_LEDGER_BYTES * 2 + 1)
    try:
        with pytest.raises(ValueError, match='Unsafe SQLite rollback journal'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert db.read_bytes() == original
        assert target.read_bytes() == b'protected-data'
    finally:
        if kind == 'directory':
            journal.rmdir()
        else:
            journal.unlink()
    assert inspect_ledger(db)['event_count'] == 0


def test_initialize_rejects_orphan_rollback_journal(tmp_path):
    db = tmp_path / 'new.sqlite'
    journal = ledger.Path(str(db) + '-journal')
    journal.symlink_to(tmp_path / 'missing-target')
    try:
        with pytest.raises(ValueError, match='Unsafe SQLite rollback journal'):
            initialize_ledger(db)
        assert not db.exists()
    finally:
        journal.unlink()


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_rollback_journal_swap_during_open_fails_closed(db, tmp_path, monkeypatch, operation):
    """Recheck journal paths after sqlite3.connect before SQL or writes."""
    journal = ledger.Path(str(db) + '-journal')
    target = tmp_path / 'protected'
    target.write_bytes(b'protected-data')
    original = db.read_bytes()
    real_connect = ledger.sqlite3.connect

    def swapped_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        journal.symlink_to(target)
        return conn

    monkeypatch.setattr(ledger.sqlite3, 'connect', swapped_connect)
    try:
        with pytest.raises(ValueError, match='Unsafe SQLite rollback journal'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert db.read_bytes() == original
        assert target.read_bytes() == b'protected-data'
    finally:
        monkeypatch.setattr(ledger.sqlite3, 'connect', real_connect)
        journal.unlink()
    assert inspect_ledger(db)['event_count'] == 0


@pytest.mark.parametrize('mode', [0o666, 0o620])
@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_writable_by_group_or_others_rollback_journal_is_quarantined(db, mode, operation):
    """Do not trust a pre-existing journal writable by another OS identity."""
    journal = ledger.Path(str(db) + '-journal')
    journal.write_bytes(b'untrusted-journal')
    journal.chmod(mode)
    original = db.read_bytes()
    try:
        with pytest.raises(ValueError, match='Unsafe SQLite rollback journal'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert journal.read_bytes() == b'untrusted-journal'
        assert db.read_bytes() == original
    finally:
        journal.unlink()
    assert inspect_ledger(db)['event_count'] == 0


def test_initialize_refuses_group_writable_orphan_rollback_journal(tmp_path):
    db = tmp_path / 'orphan-journal.sqlite'
    journal = ledger.Path(str(db) + '-journal')
    journal.write_bytes(b'untrusted')
    journal.chmod(0o660)
    try:
        with pytest.raises(ValueError, match='Unsafe SQLite rollback journal'):
            initialize_ledger(db)
        assert not db.exists()
        assert journal.read_bytes() == b'untrusted'
    finally:
        journal.unlink()


def test_regular_private_parent_rollback_journal_does_not_disable_read(db):
    """Normal DELETE-mode crash recovery must remain possible."""
    journal = ledger.Path(str(db) + '-journal')
    journal.write_bytes(b'')
    # SQLite normally creates 0644 journals; the private 0700 parent
    # prevents access by other users even when the file is world-readable.
    journal.chmod(0o644)
    try:
        assert inspect_ledger(db)['event_count'] == 0
    finally:
        if journal.exists():
            journal.unlink()


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_ledger_path_replaced_during_audit_is_quarantined(db, tmp_path, monkeypatch, operation):
    """An audit must not approve a different pathname target than it opened."""
    original = db.read_bytes()
    moved = tmp_path / 'original-moved.sqlite'
    replacement = tmp_path / 'replacement.sqlite'
    initialize_ledger(replacement)
    replacement_bytes = replacement.read_bytes()
    real_verify = ledger._verify
    swapped = False

    def swap_after_audit(conn):
        nonlocal swapped
        result = real_verify(conn)
        if not swapped:
            db.rename(moved)
            replacement.rename(db)
            swapped = True
        return result

    monkeypatch.setattr(ledger, '_verify', swap_after_audit)
    try:
        with pytest.raises(ValueError, match='storage identity changed during operation'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert db.read_bytes() == replacement_bytes
        assert moved.read_bytes() == original
    finally:
        monkeypatch.setattr(ledger, '_verify', real_verify)
        if moved.exists():
            db.unlink()
            moved.rename(db)
    assert inspect_ledger(db)['event_count'] == 0


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_ledger_permissions_relaxed_during_audit_are_quarantined(db, monkeypatch, operation):
    """Do not trust a ledger whose privacy changes during a long audit."""
    original = db.read_bytes()
    real_verify = ledger._verify

    def relax_after_audit(conn):
        result = real_verify(conn)
        db.chmod(0o644)
        return result

    monkeypatch.setattr(ledger, '_verify', relax_after_audit)
    try:
        with pytest.raises(ValueError, match='private mode 0600'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert db.read_bytes() == original
    finally:
        monkeypatch.setattr(ledger, '_verify', real_verify)
        db.chmod(0o600)
    assert inspect_ledger(db)['event_count'] == 0


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_rollback_journal_injected_during_audit_is_quarantined(
        db, tmp_path, monkeypatch, operation):
    """Reject a suspicious sidecar before accepting an audit or first write."""
    original = db.read_bytes()
    target = tmp_path / 'protected'
    target.write_bytes(b'protected')
    journal = ledger.Path(str(db) + '-journal')
    real_verify = ledger._verify

    def inject_after_audit(conn):
        result = real_verify(conn)
        journal.symlink_to(target)
        return result

    monkeypatch.setattr(ledger, '_verify', inject_after_audit)
    try:
        with pytest.raises(ValueError, match='Unsafe SQLite rollback journal'):
            if operation == 'inspect':
                inspect_ledger(db)
            else:
                prep(db)
        assert db.read_bytes() == original
        assert target.read_bytes() == b'protected'
    finally:
        monkeypatch.setattr(ledger, '_verify', real_verify)
        if journal.is_symlink():
            journal.unlink()
    assert inspect_ledger(db)['event_count'] == 0


@pytest.mark.parametrize('intermediate', ['directory', 'symlink'])
@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_parent_traversal_path_is_rejected_before_sqlite_open(
        db, tmp_path, intermediate, operation):
    """A/../ledger traverses A, even if a pathname-only symlink scan misses A."""
    original = db.read_bytes()
    nested = tmp_path / 'nested'
    nested.mkdir()
    alias = tmp_path / 'alias'
    if intermediate == 'symlink':
        alias.symlink_to(nested, target_is_directory=True)
    else:
        alias.mkdir()
    traversal = alias / '..' / db.name
    assert traversal.read_bytes() == original  # OS resolves the path successfully
    with pytest.raises(ValueError, match='parent traversal components'):
        if operation == 'inspect':
            inspect_ledger(traversal)
        else:
            prep(traversal)
    assert db.read_bytes() == original
    assert inspect_ledger(db)['event_count'] == 0


@pytest.mark.parametrize('intermediate', ['directory', 'symlink'])
def test_initialization_rejects_parent_traversal_without_creating(
        tmp_path, intermediate):
    nested = tmp_path / 'nested'
    nested.mkdir()
    alias = tmp_path / 'alias'
    if intermediate == 'symlink':
        alias.symlink_to(nested, target_is_directory=True)
    else:
        alias.mkdir()
    target = tmp_path / 'new-ledger.sqlite'
    with pytest.raises(ValueError, match='parent traversal components'):
        initialize_ledger(alias / '..' / target.name)
    assert not target.exists()


@pytest.mark.parametrize('suffix', ['-journal', '-wal', '-shm',
                                    '-JOURNAL', '-WaL', '-ShM'])
def test_reserved_sqlite_sidecar_filename_rejected_before_creation_or_open(
        tmp_path, suffix):
    """A ledger must not alias the recovery sidecar of another SQLite DB."""
    alias = tmp_path / ('other.sqlite' + suffix)
    with pytest.raises(ValueError, match='SQLite sidecar suffix'):
        initialize_ledger(alias)
    assert not alias.exists()

    original = tmp_path / 'safe.sqlite'
    initialize_ledger(original)
    original.rename(alias)
    unchanged = alias.read_bytes()
    with pytest.raises(ValueError, match='SQLite sidecar suffix'):
        inspect_ledger(alias)
    with pytest.raises(ValueError, match='SQLite sidecar suffix'):
        prep(alias)
    assert alias.read_bytes() == unchanged
    assert not (tmp_path / 'other.sqlite').exists()

@pytest.mark.parametrize('suffix', ['-mj', '-mj1234abcd', '-MJABCDEF01', '-mJ0f0f'])
def test_sqlite_super_journal_alias_rejected_before_creation_or_open(tmp_path, suffix):
    """A ledger cannot masquerade as another database's super-journal."""
    alias = tmp_path / ('other.sqlite' + suffix)
    with pytest.raises(ValueError, match='SQLite sidecar suffix'):
        initialize_ledger(alias)
    assert not alias.exists()

    original = tmp_path / 'safe.sqlite'
    initialize_ledger(original)
    original.rename(alias)
    unchanged = alias.read_bytes()
    with pytest.raises(ValueError, match='SQLite sidecar suffix'):
        inspect_ledger(alias)
    with pytest.raises(ValueError, match='SQLite sidecar suffix'):
        prep(alias)
    assert alias.read_bytes() == unchanged
    assert not (tmp_path / 'other.sqlite').exists()


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_initialize_quarantines_sidecar_injected_after_sqlite_open(
        tmp_path, monkeypatch, suffix):
    """Schema creation must not trust only the earlier SQLite-open preflight."""
    db = tmp_path / 'init-race.sqlite'
    sidecar = ledger.Path(str(db) + suffix)
    protected = tmp_path / 'protected-evidence'
    protected.write_bytes(b'keep-original')
    real_connect = ledger._connect

    def inject_after_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        sidecar.symlink_to(protected)
        return conn

    monkeypatch.setattr(ledger, '_connect', inject_after_connect)
    with pytest.raises(ValueError, match=(
            'Unreviewed SQLite WAL/SHM sidecar' if suffix != '-journal'
            else 'Unsafe SQLite rollback journal')):
        initialize_ledger(db)
    assert db.exists()  # Failed initialization is quarantined, never deleted.
    assert sidecar.is_symlink()
    assert protected.read_bytes() == b'keep-original'


def test_initialize_quarantines_growth_after_sqlite_open(tmp_path, monkeypatch):
    """Reject an oversized new database before schema DDL is attempted."""
    db = tmp_path / 'init-growth.sqlite'
    real_connect = ledger._connect

    def grow_after_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        with db.open('r+b') as f:
            f.truncate(ledger.MAX_LEDGER_BYTES + 1)
        return conn

    monkeypatch.setattr(ledger, '_connect', grow_after_connect)
    with pytest.raises(ValueError, match='reviewed byte capacity'):
        initialize_ledger(db)
    assert db.exists()
    assert db.stat().st_size == ledger.MAX_LEDGER_BYTES + 1


def test_unknown_submission_quarantines_new_same_account_intents(db):
    """A second client ID cannot hide an unresolved first broker attempt."""
    prep(db)
    attempt(db)
    with pytest.raises(ValueError, match='Unresolved broker submission'):
        prepare_intent(db, recorded_at_ms=102, **(KEY | {'client_order_id': 'order-2', 'intent_sha256': E}))
    snapshot = inspect_ledger(db)
    assert snapshot['event_count'] == 2
    assert snapshot['order_count'] == 1
    assert snapshot['orders'][0]['status'] == 'ATTEMPT_UNKNOWN'


def test_prepared_second_order_cannot_attempt_during_first_unknown(db):
    """Preparing before the ambiguity must not bypass the account fence."""
    prep(db)
    prep(db, client_order_id='order-2', intent_sha256=E)
    attempt(db)
    with pytest.raises(ValueError, match='Unresolved broker submission'):
        attempt(db, client_order_id='order-2', intent_sha256=E)
    assert inspect_ledger(db)['event_count'] == 3
    # Declared terminal reconciliation clears this *local* pending status,
    # but is NOT authenticated broker proof or permission to execute.
    reconcile(db)
    assert mark_attempt_unknown(db, recorded_at_ms=103, **(KEY | {'client_order_id': 'order-2', 'intent_sha256': E}))['may_submit_real_order'] is False


def test_unknown_quarantine_is_scoped_to_broker_and_account(db):
    prep(db)
    attempt(db)
    # A different account or broker label has a separate evidence namespace.
    assert prepare_intent(db, recorded_at_ms=102, **(KEY | {'account_alias': 'other-account'}))['may_submit_paper_order'] is False
    assert prepare_intent(db, recorded_at_ms=103, **(KEY | {'broker': 'T212-STOCKSISA-DEMO'}))['may_submit_real_order'] is False
    assert mark_attempt_unknown(db, recorded_at_ms=104, **(KEY | {'account_alias': 'other-account'}))['may_submit_real_order'] is False
    assert mark_attempt_unknown(db, recorded_at_ms=105, **(KEY | {'broker': 'T212-STOCKSISA-DEMO'}))['may_submit_real_order'] is False


def test_concurrent_distinct_attempts_only_one_becomes_unknown(db):
    prep(db)
    prep(db, client_order_id='order-2', intent_sha256=E)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(attempt, db),
            pool.submit(attempt, db, client_order_id='order-2', intent_sha256=E),
        ]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except ValueError as exc:
                assert 'Unresolved broker submission' in str(exc)
                results.append(None)
    assert sum(result is not None for result in results) == 1
    snapshot = inspect_ledger(db)
    assert snapshot['event_count'] == 3
    assert sum(order['status'] == 'ATTEMPT_UNKNOWN' for order in snapshot['orders']) == 1


@pytest.mark.parametrize('payload', [b'', b'untrusted-orphan-journal'])
def test_initialization_rejects_regular_orphan_rollback_journal(tmp_path, payload):
    """A fresh database cannot safely inherit a former database's journal."""
    db = tmp_path / 'new-with-orphan.sqlite'
    journal = ledger.Path(str(db) + '-journal')
    journal.write_bytes(payload)
    journal.chmod(0o644)
    with pytest.raises(ValueError, match='Orphan SQLite rollback journal'):
        initialize_ledger(db)
    assert not db.exists()
    assert journal.read_bytes() == payload


def test_initialization_rejects_regular_journal_injected_after_open(tmp_path, monkeypatch):
    """Do not begin schema DDL if a valid-looking orphan appears after open."""
    db = tmp_path / 'new-race.sqlite'
    journal = ledger.Path(str(db) + '-journal')
    real_connect = ledger._connect

    def inject_after_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        journal.write_bytes(b'foreign-recovery-evidence')
        journal.chmod(0o644)
        return conn

    monkeypatch.setattr(ledger, '_connect', inject_after_connect)
    with pytest.raises(ValueError, match='Orphan SQLite rollback journal'):
        initialize_ledger(db)
    assert db.exists()  # Partial initialization remains for manual review.
    assert journal.read_bytes() == b'foreign-recovery-evidence'
    monkeypatch.setattr(ledger, '_connect', real_connect)
    with pytest.raises(ValueError, match='schema'):
        inspect_ledger(db)


def _inject_rehashed_event(db, *, broker, account, order, event, evidence, stamp):
    """Synthetic corruption: valid local hashes and matching projection, illegal history."""
    with sqlite3.connect(db) as conn:
        seq, previous = conn.execute(
            'SELECT seq,event_hash FROM events ORDER BY seq DESC LIMIT 1'
        ).fetchone()
        seq += 1
        digest = ledger._event_hash(seq, broker, account, order, event,
                                    evidence, stamp, previous)
        conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                     (seq, broker, account, order, event, evidence, stamp,
                      previous, digest))
        if event == 'PREPARED':
            conn.execute('INSERT INTO intents VALUES (?,?,?,?,?)',
                         (broker, account, order, evidence, event))
        else:
            conn.execute('UPDATE intents SET status=? WHERE broker=? AND account=? AND order_id=?',
                         (event, broker, account, order))


@pytest.mark.parametrize('injected_event', ['PREPARED', 'ATTEMPT_UNKNOWN'])
@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_rehashed_history_cannot_bypass_account_unknown_quarantine(
        db, injected_event, operation):
    """A matching final projection and recomputed hashes must not legalize overlap."""
    prep(db)
    if injected_event == 'ATTEMPT_UNKNOWN':
        prep(db, client_order_id='order-2', intent_sha256=E)
    attempt(db)
    _inject_rehashed_event(
        db, broker=KEY['broker'], account=KEY['account_alias'],
        order='order-2', event=injected_event, evidence=E, stamp=102)
    with sqlite3.connect(db) as conn:
        before = conn.execute('SELECT count(*) FROM events').fetchone()[0]
    with pytest.raises(ValueError, match='Unresolved broker submission for account'):
        if operation == 'inspect':
            inspect_ledger(db)
        else:
            prepare_intent(db, broker=KEY['broker'], account_alias=KEY['account_alias'],
                           client_order_id='order-3', intent_sha256='c' * 64,
                           recorded_at_ms=103)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0] == before


def test_reconciled_account_history_allows_new_local_evidence_but_not_execution(db):
    prep(db)
    attempt(db)
    reconcile(db)
    result = prepare_intent(db, broker=KEY['broker'], account_alias=KEY['account_alias'],
                            client_order_id='order-2', intent_sha256=E,
                            recorded_at_ms=103)
    assert result['may_submit_paper_order'] is False
    assert result['may_submit_real_order'] is False
    assert inspect_ledger(db)['event_count'] == 4


def test_zero_digest_is_not_valid_intent_evidence(db):
    """A zero-filled placeholder is not a verified intent fingerprint."""
    with pytest.raises(ValueError, match='nonzero lowercase SHA-256'):
        prep(db, intent_sha256='0' * 64)
    assert inspect_ledger(db)['event_count'] == 0


def test_zero_digest_is_not_valid_declared_reconciliation_evidence(db):
    """Even local terminal claims require a non-placeholder evidence digest."""
    prep(db)
    attempt(db)
    with pytest.raises(ValueError, match='nonzero lowercase SHA-256'):
        record_declared_reconciliation(
            db, recorded_at_ms=102, evidence_sha256='0' * 64,
            outcome='FILLED', **{k: v for k, v in KEY.items() if k != 'intent_sha256'})
    assert inspect_ledger(db)['orders'][0]['status'] == 'ATTEMPT_UNKNOWN'
    assert inspect_ledger(db)['event_count'] == 2


def test_rehashed_history_with_zero_evidence_fails_closed(db):
    """Recomputed local hashes cannot make an all-zero evidence digest valid."""
    prep(db)
    _inject_rehashed_event(
        db, broker=KEY['broker'], account='other-account',
        order='order-2', event='PREPARED', evidence='0' * 64, stamp=101)
    with pytest.raises(ValueError, match='nonzero lowercase SHA-256'):
        inspect_ledger(db)
    with pytest.raises(ValueError, match='nonzero lowercase SHA-256'):
        prepare_intent(db, broker=KEY['broker'], account_alias='other-account',
                       client_order_id='order-3', intent_sha256=E,
                       recorded_at_ms=102)


def test_reconciliation_cannot_reuse_original_intent_fingerprint(db):
    """A prepared-intent digest is not a broker reconciliation receipt."""
    prep(db)
    attempt(db)
    with pytest.raises(ValueError, match='reuses intent fingerprint'):
        reconcile(db, evidence_sha256=H)
    audited = inspect_ledger(db)
    assert audited['event_count'] == 2
    assert audited['orders'][0]['status'] == 'ATTEMPT_UNKNOWN'
    assert audited['may_submit_real_order'] is False


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_rehashed_reconciliation_with_reused_intent_digest_is_rejected(db, operation):
    """Matching projection and locally recomputed hashes cannot clear quarantine."""
    prep(db)
    attempt(db)
    _inject_rehashed_event(
        db, broker=KEY['broker'], account=KEY['account_alias'],
        order=KEY['client_order_id'], event='RECONCILED_FILLED',
        evidence=H, stamp=102)
    with pytest.raises(ValueError, match='reuses intent fingerprint'):
        if operation == 'inspect':
            inspect_ledger(db)
        else:
            prepare_intent(
                db, broker=KEY['broker'], account_alias=KEY['account_alias'],
                client_order_id='order-2', intent_sha256=E, recorded_at_ms=103)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0] == 3
