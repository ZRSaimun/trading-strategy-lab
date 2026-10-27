"""Offline, fail-closed SQLite fence for non-idempotent broker submissions.

Records paper/demo/live-labelled *evidence only*. No network, credentials,
orders, approval, broker authentication or execution permission exists here.
The irreversible UNKNOWN transition must be committed BEFORE a future adapter
attempts a non-idempotent submission; it can never be retried by this module.
"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1
MAX_EVENTS = 10000
MAX_TIME = 8_640_000_000_000_000
ZERO = '0' * 64
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
BROKERS = frozenset({'PAPER-LOCAL', 'T212-INVEST-DEMO', 'T212-STOCKSISA-DEMO',
                     'T212-INVEST-LIVE', 'T212-STOCKSISA-LIVE'})
EVENTS = frozenset({'PREPARED', 'ATTEMPT_UNKNOWN', 'RECONCILED_FILLED',
                    'RECONCILED_REJECTED', 'RECONCILED_CANCELLED'})

# Compare reviewed DDL, not just object names: a same-named replacement index
# or permissive table must never silently pass a safety-critical audit.
EXPECTED_SCHEMA_OBJECTS = {
    ('table', 'intents'): (
        'CREATE TABLE intents (broker TEXT NOT NULL, account TEXT NOT NULL, '
        'order_id TEXT NOT NULL, intent_sha TEXT NOT NULL, status TEXT NOT NULL, '
        'PRIMARY KEY (broker, account, order_id)) WITHOUT ROWID'),
    ('index', 'unique_account_intent'): (
        'CREATE UNIQUE INDEX unique_account_intent ON intents (broker, account, intent_sha)'),
    ('table', 'events'): (
        'CREATE TABLE events (seq INTEGER PRIMARY KEY, broker TEXT NOT NULL, '
        'account TEXT NOT NULL, order_id TEXT NOT NULL, event TEXT NOT NULL, '
        'evidence_sha TEXT NOT NULL, recorded_at_ms INTEGER NOT NULL, '
        'prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL)'),
}


def _id(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f'{field}: invalid identifier')
    return value


def _sha(value, field):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f'{field}: expected lowercase SHA-256 hex')
    return value


def _time(value):
    if type(value) is not int or not 0 <= value <= MAX_TIME:
        raise ValueError('recorded_at_ms: invalid UTC epoch milliseconds')
    return value


def _identity(broker, account_alias, client_order_id):
    if _id(broker, 'broker') not in BROKERS:
        raise ValueError('Unsupported broker label; CFD API execution is unsupported')
    return (broker, _id(account_alias, 'account_alias'),
            _id(client_order_id, 'client_order_id'))


def _event_hash(seq, broker, account, order, event, evidence, stamp, previous):
    payload = [SCHEMA_VERSION, seq, broker, account, order, event,
               evidence, stamp, previous]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':'),
                                     ensure_ascii=True).encode('ascii')).hexdigest()


def _connect(path):
    if not isinstance(path, (str, Path)):
        raise ValueError('Database path required')
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ValueError('Existing regular ledger file required; initialize separately')
    conn = sqlite3.connect(str(p), timeout=5, isolation_level=None)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


def initialize_ledger(path):
    """Explicit one-time creation. Never silently recreate or repair an existing DB."""
    p = Path(path)
    if p.exists() or p.is_symlink():
        raise ValueError('Ledger already exists; refusing overwrite')
    # Exclusive create avoids replacing an existing file. SQLite opens it next.
    with p.open('xb'):
        pass
    try:
        conn = sqlite3.connect(str(p), isolation_level=None)
        try:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('BEGIN EXCLUSIVE')
            conn.execute('CREATE TABLE intents (broker TEXT NOT NULL, account TEXT NOT NULL, '
                         'order_id TEXT NOT NULL, intent_sha TEXT NOT NULL, status TEXT NOT NULL, '
                         'PRIMARY KEY (broker, account, order_id)) WITHOUT ROWID')
            conn.execute('CREATE UNIQUE INDEX unique_account_intent ON intents (broker, account, intent_sha)')
            conn.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, broker TEXT NOT NULL, '
                         'account TEXT NOT NULL, order_id TEXT NOT NULL, event TEXT NOT NULL, '
                         'evidence_sha TEXT NOT NULL, recorded_at_ms INTEGER NOT NULL, '
                         'prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL)')
            conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            conn.execute('COMMIT')
        finally:
            conn.close()
    except BaseException:
        # Never auto-remove a possibly valuable partial DB. Quarantine manually.
        raise


def _verify(conn):
    if conn.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise ValueError('Unexpected ledger schema version')
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('SQLite integrity check failed')
    objects = {(kind, name): sql for kind, name, sql in conn.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    if objects != EXPECTED_SCHEMA_OBJECTS:
        raise ValueError('Ledger schema objects differ from reviewed DDL')
    # Bound the SQL result before fetching: a hostile oversized ledger must not
    # allocate arbitrary process memory prior to the MAX_EVENTS check.
    rows = conn.execute('SELECT seq,broker,account,order_id,event,evidence_sha,'
                        'recorded_at_ms,prev_hash,event_hash FROM events ORDER BY seq '
                        'LIMIT ?', (MAX_EVENTS + 1,)).fetchall()
    if len(rows) > MAX_EVENTS:
        raise ValueError('Ledger event capacity reached; no automatic truncation')
    state = {}
    previous = ZERO
    last_time = -1
    for n, row in enumerate(rows, 1):
        seq, broker, account, order, event, evidence, stamp, prev, digest = row
        _identity(broker, account, order)
        _sha(evidence, 'evidence_sha')
        _time(stamp)
        if seq != n or event not in EVENTS or prev != previous or stamp < last_time:
            raise ValueError('Ledger audit sequence or clock is inconsistent')
        if digest != _event_hash(seq, broker, account, order, event, evidence, stamp, prev):
            raise ValueError('Ledger audit hash mismatch')
        key = (broker, account, order)
        old = state.get(key)
        if event == 'PREPARED':
            if old is not None:
                raise ValueError('Repeated preparation in audit')
            state[key] = (evidence, 'PREPARED')
        elif event == 'ATTEMPT_UNKNOWN':
            if old is None or old[1] != 'PREPARED' or evidence != old[0]:
                raise ValueError('Invalid attempt transition')
            state[key] = (old[0], 'ATTEMPT_UNKNOWN')
        else:
            if old is None or old[1] != 'ATTEMPT_UNKNOWN':
                raise ValueError('Invalid reconciliation transition')
            state[key] = (old[0], event)
        previous = digest
        last_time = stamp
    actual = {(b, a, o): (h, s) for b, a, o, h, s in conn.execute(
        'SELECT broker,account,order_id,intent_sha,status FROM intents')}
    if state != actual:
        raise ValueError('Ledger projection differs from audit history')
    return len(rows), previous, last_time, state


def _append(conn, key, event, evidence, stamp, count, previous):
    if count >= MAX_EVENTS:
        raise ValueError('Ledger event capacity reached')
    seq = count + 1
    digest = _event_hash(seq, *key, event, evidence, stamp, previous)
    conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                 (seq, *key, event, evidence, stamp, previous, digest))
    return digest


def _write(path, key, event, evidence, stamp):
    conn = _connect(path)
    try:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        count, previous, last_time, state = _verify(conn)
        if stamp < last_time:
            raise ValueError('Clock regression; cannot append evidence')
        old = state.get(key)
        if event == 'PREPARED':
            if old is not None:
                raise ValueError('Duplicate client order ID, even if intent is identical')
            conn.execute('INSERT INTO intents VALUES (?,?,?,?,?)', (*key, evidence, event))
        elif event == 'ATTEMPT_UNKNOWN':
            if old is None or old != (evidence, 'PREPARED'):
                raise ValueError('Unknown or already attempted order; retry forbidden')
            conn.execute('UPDATE intents SET status=? WHERE broker=? AND account=? AND order_id=?',
                         (event, *key))
        else:
            if old is None or old[1] != 'ATTEMPT_UNKNOWN':
                raise ValueError('Reconciliation requires one unresolved attempt')
            conn.execute('UPDATE intents SET status=? WHERE broker=? AND account=? AND order_id=?',
                         (event, *key))
        digest = _append(conn, key, event, evidence, stamp, count, previous)
        conn.execute('COMMIT')
        return {'status': event, 'audit_sha256': digest,
                'may_submit_paper_order': False, 'may_submit_real_order': False,
                'requires_independent_reconciliation': True}
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


def prepare_intent(path, *, broker, account_alias, client_order_id,
                   intent_sha256, recorded_at_ms):
    return _write(path, _identity(broker, account_alias, client_order_id),
                  'PREPARED', _sha(intent_sha256, 'intent_sha256'), _time(recorded_at_ms))


def mark_attempt_unknown(path, *, broker, account_alias, client_order_id,
                         intent_sha256, recorded_at_ms):
    """Commit UNKNOWN before ANY external submission. Never grants permission."""
    return _write(path, _identity(broker, account_alias, client_order_id),
                  'ATTEMPT_UNKNOWN', _sha(intent_sha256, 'intent_sha256'), _time(recorded_at_ms))


def record_declared_reconciliation(path, *, broker, account_alias, client_order_id,
                                    outcome, evidence_sha256, recorded_at_ms):
    if outcome not in ('FILLED', 'REJECTED', 'CANCELLED'):
        raise ValueError('Invalid declared outcome')
    return _write(path, _identity(broker, account_alias, client_order_id),
                  'RECONCILED_' + outcome, _sha(evidence_sha256, 'evidence_sha256'),
                  _time(recorded_at_ms))


def inspect_ledger(path):
    """Read-only audit, never a clearance or submission capability."""
    conn = _connect(path)
    try:
        conn.execute('BEGIN')
        count, digest, _, state = _verify(conn)
        conn.execute('COMMIT')
        return {'schema': 'paper-submission-attempt-ledger-v1', 'event_count': count,
                'order_count': len(state), 'audit_tip_sha256': digest,
                'orders': [{'broker': b, 'account_alias': a, 'client_order_id': o,
                            'status': v[1]} for (b, a, o), v in sorted(state.items())],
                'status': 'HOLD_RECONCILIATION',
                'may_submit_paper_order': False, 'may_submit_real_order': False,
                'warning': 'Local hashes are not externally anchored; declared reconciliation is not broker authentication.'}
    finally:
        conn.close()
