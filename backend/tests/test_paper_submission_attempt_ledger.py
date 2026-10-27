"""Synthetic offline tests: no network, broker credentials or real orders."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

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
    with pytest.raises(ValueError, match='index'):
        inspect_ledger(db)


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
