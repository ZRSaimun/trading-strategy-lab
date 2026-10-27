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
    assert x['may_submit_real_order'] is False


def test_lifecycle_and_no_execution(db):
    for x in (prep(db), attempt(db), reconcile(db)):
        assert x['may_submit_paper_order'] is False
        assert x['may_submit_real_order'] is False
    x = inspect_ledger(db)
    assert x['event_count'] == 3
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
