"""Offline, fail-closed SQLite fence for non-idempotent broker submissions.

Records paper/demo/live-labelled *evidence only*. No network, credentials,
orders, approval, broker authentication or execution permission exists here.
The irreversible UNKNOWN transition must be committed BEFORE a future adapter
attempts a non-idempotent submission; it can never be retried by this module.
"""
import hashlib
import os
import json
import re
import sqlite3
import stat
from pathlib import Path

SCHEMA_VERSION = 1
MAX_EVENTS = 10000
# Local SQLite evidence only: bound database bytes and decoded SQLite values
# before scanning an untrusted or corrupted ledger. No automatic truncation.
MAX_LEDGER_BYTES = 32 * 1024 * 1024
MAX_SQLITE_VALUE_BYTES = 4096
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


def _private_parent(path):
    """Reject unsafe SQLite sidecar directories before opening any ledger."""
    if os.name != 'posix' or not hasattr(os, 'geteuid'):
        raise ValueError('Ledger storage requires POSIX owner and mode checks')
    parent = path.absolute().parent
    # A symlink anywhere in the directory path can redirect SQLite's journal
    # and database opens even when the final ledger path is not a symlink.
    if any(part.is_symlink() for part in (parent, *parent.parents)):
        raise ValueError('Ledger parent path must not contain symlinks')
    try:
        info = parent.lstat()
    except OSError as exc:
        raise ValueError('Ledger private parent directory unavailable') from exc
    if (not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_uid != os.geteuid()):
        raise ValueError('Ledger parent must be a service-owned private directory (0700)')
    return (info.st_dev, info.st_ino)


def _private_file(info):
    """Prevent other users and hardlinks from bypassing the evidence boundary."""
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Existing regular ledger file required; initialize separately')
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Ledger file must have private mode 0600')
    if info.st_uid != os.geteuid():
        raise ValueError('Ledger file must be owned by the service user')
    if info.st_nlink != 1:
        raise ValueError('Ledger file hardlinks are forbidden')


def _reject_wal_sidecars(path):
    """Refuse unreviewed SQLite WAL/SHM evidence, including dangling symlinks.

    A WAL may contain committed transactions absent from the main DB file.
    This research ledger uses rollback journaling only; never auto-delete or
    checkpoint a sidecar whose provenance has not been established.
    """
    if any(os.path.lexists(str(path) + suffix) for suffix in ('-wal', '-shm')):
        raise ValueError('Unreviewed SQLite WAL/SHM sidecar; quarantine ledger')


def _validate_rollback_journal(path):
    """Allow ordinary SQLite crash recovery, reject unsafe journal path types.

    A hot DELETE-mode rollback journal may be essential for recovery; never
    remove or rewrite it. The private parent prevents other users creating
    sidecars, but a pre-existing symlink, hardlink or special file must not be
    handed to SQLite as an implicit read/write target. Reject group/other\n    writable journal modes, while allowing SQLite's ordinary 0644 journals\n    inside the mandatory private 0700 parent directory.
    """
    journal = Path(str(path) + '-journal')
    try:
        info = journal.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError('SQLite rollback journal cannot be inspected') from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > MAX_LEDGER_BYTES * 2):
        raise ValueError('Unsafe SQLite rollback journal; quarantine ledger')


def _connect(path, *, read_only=False):
    if not isinstance(path, (str, Path)):
        raise ValueError('Database path required')
    p = Path(path)
    parent_identity = _private_parent(p)
    if p.is_symlink() or not p.is_file():
        raise ValueError('Existing regular ledger file required; initialize separately')
    try:
        before = p.lstat()
    except FileNotFoundError as exc:
        raise ValueError('Ledger disappeared before SQLite open') from exc
    _private_file(before)
    _reject_wal_sidecars(p)
    _validate_rollback_journal(p)
    if before.st_size > MAX_LEDGER_BYTES:
        raise ValueError('Ledger file exceeds reviewed byte capacity')
    # mode=ro/rw prevents sqlite3's default rwc mode from recreating a ledger
    # removed between the filesystem preflight and SQLite's actual open.
    # Use a URI to preserve escaping of spaces, '?' and '#' in the path.
    uri = p.absolute().as_uri() + ('?mode=ro' if read_only else '?mode=rw')
    conn = sqlite3.connect(uri, timeout=5, isolation_level=None, uri=True)
    try:
        # A replacement or symlink introduced after preflight must not pass
        # silently into a ledger transition. This is a best-effort identity
        # check, NOT an atomic openat/O_NOFOLLOW guarantee against a privileged
        # attacker who swaps the file away and back during SQLite's open.
        try:
            after = p.lstat()
        except FileNotFoundError as exc:
            raise ValueError('Ledger disappeared during SQLite open') from exc
        if _private_parent(p) != parent_identity:
            raise ValueError('Ledger parent identity changed during SQLite open')
        if (not stat.S_ISREG(after.st_mode)
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('Ledger file identity changed during SQLite open')
        _private_file(after)
        _reject_wal_sidecars(p)
        _validate_rollback_journal(p)
        if after.st_size > MAX_LEDGER_BYTES:
            raise ValueError('Ledger file exceeds reviewed byte capacity')
        # Python 3.12/SQLite limits apply to values decoded from malicious rows,
        # not merely the number of rows returned by LIMIT.
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQLITE_VALUE_BYTES)
        # The on-disk SQLite header can request WAL even after sidecar files
        # have been removed. Query only: never silently switch journal modes.
        if conn.execute('PRAGMA journal_mode').fetchone() != ('delete',):
            raise ValueError('Unexpected SQLite journal mode; quarantine ledger')
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
    except BaseException:
        conn.close()
        raise
    return conn


def initialize_ledger(path):
    """Explicit one-time creation. Never silently recreate or repair an existing DB."""
    p = Path(path)
    parent_identity = _private_parent(p)
    if p.exists() or p.is_symlink():
        raise ValueError('Ledger already exists; refusing overwrite')
    _reject_wal_sidecars(p)
    _validate_rollback_journal(p)
    # Create mode 0600 regardless of a permissive process umask. O_EXCL
    # refuses an existing file, including a symlink. Never auto-recreate it.
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                 | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        created = os.fstat(fd)
        _private_file(created)
    finally:
        os.close(fd)

    def require_original_file():
        if _private_parent(p) != parent_identity:
            raise ValueError('Ledger parent identity changed during initialization')
        try:
            current = p.lstat()
        except FileNotFoundError as exc:
            raise ValueError('New ledger disappeared during initialization') from exc
        if (not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino)
                != (created.st_dev, created.st_ino)):
            raise ValueError('New ledger file identity changed during initialization')
        _private_file(current)

    try:
        # Existing-only SQLite URI: a removed freshly created file must not
        # silently become a different, empty ledger at connection time.
        conn = _connect(p)
        try:
            require_original_file()
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
            require_original_file()
            conn.execute('COMMIT')
            require_original_file()
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
    # A hostile projection may contain far more rows than the audit. Never
    # materialize an unbounded intents table before discovering corruption.
    projection_rows = conn.execute(
        'SELECT broker,account,order_id,intent_sha,status FROM intents LIMIT ?',
        (MAX_EVENTS + 1,)).fetchall()
    if len(projection_rows) > MAX_EVENTS:
        raise ValueError('Ledger intent capacity reached; no automatic truncation')
    actual = {(b, a, o): (h, s) for b, a, o, h, s in projection_rows}
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
    conn = _connect(path, read_only=True)
    try:
        conn.execute('BEGIN')
        count, digest, last_time, state = _verify(conn)
        conn.execute('COMMIT')
        return {'schema': 'paper-submission-attempt-ledger-v1', 'event_count': count,
                'order_count': len(state), 'audit_tip_sha256': digest,
                'last_recorded_at_ms': last_time if count else None,
                'orders': [{'broker': b, 'account_alias': a, 'client_order_id': o,
                            'status': v[1]} for (b, a, o), v in sorted(state.items())],
                'status': 'HOLD_RECONCILIATION',
                'may_submit_paper_order': False, 'may_submit_real_order': False,
                'warning': 'Local hashes are not externally anchored; declared reconciliation is not broker authentication.'}
    finally:
        conn.close()
