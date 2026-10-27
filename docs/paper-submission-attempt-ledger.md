# Non-idempotent broker submission attempt ledger (offline safety research)

The Python module at backend/app/paper_submission_attempt_ledger.py is an opt-in, standalone SQLite evidence ledger. It has **no API route, network access, broker credential handling, trading permission or execution capability**. It does not place even demo orders. Its purpose is to make ambiguous broker-submission outcomes visible and non-retryable across process restarts.

## State machine

PREPARED → ATTEMPT_UNKNOWN → one of RECONCILED_FILLED, RECONCILED_REJECTED, RECONCILED_CANCELLED.

An attempt must be committed to ATTEMPT_UNKNOWN **before** any future adapter sends a non-idempotent request. A crash before sending will conservatively quarantine an unsubmitted intent. A crash during or after sending must never cause an automatic retry. Even a declared terminal reconciliation cannot reuse the order ID or the identical intent fingerprint on the same broker/account. There is no release/submit method. Every result explicitly sets both execution flags to false.

An operator may explicitly create a local database with initialize_ledger(path), then call prepare_intent, mark_attempt_unknown, record_declared_reconciliation and inspect_ledger. These methods accept bounded identifiers, SHA-256 hashes and UTC epoch milliseconds; they must not receive API keys, raw order bodies, PII or trading account numbers. SQLite BEGIN IMMEDIATE serializes competing writers, synchronous=FULL and commit-before-send favor durable quarantine, and an append-only, locally hash-linked event log detects many accidental changes. An exact event replay must match the current intent table. Corruption and clock regression fail closed. The ledger never silently repairs or truncates a file.

**Important limitations:** Hash chains without a separately trusted external anchor cannot detect a privileged attacker who rewrites all rows/hashes or restores an old complete backup. Local SQLite does not establish remote broker inventory, authenticated fills, quote freshness, protective-stop acceptance, owner approval, or safe live order submission. Declared RECONCILED_* states are **not broker verified**. Filesystem durability depends on the host and storage configuration; the ledger is not a distributed consensus store. This module has no integration with the existing risk reservation or signed-approval PRs, and should not be wired into an order sender without comprehensive adversarial tests and explicit human review.

The official Trading 212 Public API documents **Invest and Stocks ISA only**, including demo. It does **not** document CFD API execution. Its beta order endpoints warn that identical POSTs may create duplicate orders. Reference: https://docs.trading212.com/api/orders/orders (checked 27 October 2026). Broker API support, credentials and live-order approval must be reverified separately for every future integration.

## Tests

Run from the repository root:

    PYTHONPATH=backend python -m pytest -q backend/tests/test_paper_submission_attempt_ledger.py

Synthetic cases cover durable restart quarantine, duplicate order/intent prevention, two-writer races, terminal state irreversibility, corrupt projection and audit events, schema mismatch, invalid inputs, symlinks and missing databases. No real or demo orders are submitted.

## Integration handoff

Before any paper broker integration: verify broker account and complete order/fill inventory from authenticated, authorized provider responses; atomically bind this ledger to persistent risk reservations, circuit breakers, quote/contract freshness, protective stops and human-specific signed approval. Reconcile unknown outcomes using authenticated order and fill history, not just the pending-order list. Use a server-owned append-only audit anchor and test crash points before/after every commit and broker request. Keep live execution disabled until individual per-order owner approval and independent release verification.

## Reviewed schema integrity (27 October 2026)

Every read and write verifies the exact reviewed SQLite `sqlite_master` DDL for both tables and the unique intent index, and rejects unexpected views, triggers or indexes. Merely recreating an index with the same name but weaker uniqueness no longer passes. Audit scans now fetch at most `MAX_EVENTS + 1` rows before rejecting oversized ledgers, avoiding unbounded `fetchall()` memory use. Regression cases cover added columns, views, indexes and a downgraded unique index. This is structural tamper detection, **not** cryptographic authentication: an attacker able to rewrite the database and recompute the unanchored hash chain can still forge history. Store externally anchored checkpoints and use authenticated broker reconciliation before any future execution integration.

## Removed-file and oversized-projection hardening (27 October 2026)

The existing-file check is not sufficient on its own: a database can disappear between the filesystem preflight and SQLite opening it. SQLite's default read/write/create mode could silently recreate a blank file. The ledger now opens existing files explicitly using SQLite URI `mode=rw` for transitions and `mode=ro` for inspection, so a missing file cannot be recreated by either operation. URI escaping is tested for reserved filename characters. This mitigates accidental removal races; it does **not** provide a portable defense against a privileged adversary replacing a file with a symlink after preflight.

Audit events and the materialized intent projection are now **both** fetched with a strict `MAX_EVENTS + 1` bound. An oversized projection fails closed before unbounded Python dictionary allocation. No automatic repair, deletion, compaction or reset is attempted. Four new synthetic tests exercise removed-file preflight races, read-only inspection versus read/write mode, projection overflow and escaped filenames. These controls remain offline evidence checks and do not authenticate a broker or permit orders.


## Bounded SQLite file and decoded values (27 October 2026)

The connection preflight now refuses an existing ledger file larger than **32 MiB**, and each SQLite connection sets `SQLITE_LIMIT_LENGTH=4096` before reading untrusted audit rows. This complements the existing `MAX_EVENTS + 1` row bound and prevents a corrupted or hostile SQLite TEXT/BLOB cell from causing unbounded Python allocation during audit verification. The limits apply equally to read-only inspection and transactional writes. Oversized files or values are quarantined by an exception; there is no automatic truncation or repair. The size cap is an engineering limit for the current 10,000-event research ledger, not a production capacity plan.

The file-size check is a preflight, **not a guarantee against concurrent file growth or filesystem path replacement**. A same-user adversary able to replace the SQLite path during opening may still exploit a time-of-check/time-of-use race; use an access-controlled, service-owned directory with no untrusted writers, external audit anchoring, and authenticated broker reconciliation. Do not deploy this ledger as a live-order gate until a platform-specific file-identity/open strategy and crash-recovery tests have been reviewed.


## SQLite path-identity race detection (27 October 2026)

Before SQLite opens an existing ledger, the connector records the regular file's device and inode using `Path.lstat()`. Immediately after SQLite opens it, and **before any SQL statement or transaction**, the connector checks the path again. A changed device/inode, newly introduced symlink, disappearance, or newly oversized file raises an exception and closes the connection. Four synthetic tests replace the path with a different regular database or symlink between preflight and SQLite opening, on both inspection and write entry points. All such attempts must fail without writing to either ledger.

**Residual risk:** These are two pathname observations, not an atomic binding of SQLite's underlying open file descriptor. A same-user adversary who can swap the file away and back between observations, or replace it later during a transaction, can still defeat the check. SQLite does not expose a portable fd-based `openat(O_NOFOLLOW)` connection through Python's standard `sqlite3` API. Initialization also remains subject to a path replacement after exclusive creation. This mitigation must **not** be described as eliminating the TOCTOU race or as production-grade authorization. Restrict directory ownership and write access, use trusted external audit anchors, and evaluate a reviewed platform-specific secure-open strategy before any broker integration.


## Private and existing-only initialization (27 October 2026)

One-time `initialize_ledger(path)` now creates the SQLite file using exclusive `os.open(O_CREAT | O_EXCL | O_WRONLY)` with requested mode **0600** (and `O_NOFOLLOW` when the platform provides it). This prevents a permissive process umask from accidentally creating a world-readable order-intent evidence file. The initial file's device/inode is captured with `fstat`. SQLite then opens that existing path through the same `mode=rw` connection guard used by subsequent writes; it must not silently recreate a file removed between exclusive creation and SQLite opening. Initialization checks the original file identity before schema creation, before commit, and immediately after commit. It refuses an unexpected replacement, symlink, or disappearance and never automatically removes or repairs the partial original.

Synthetic tests cover permissive umask, removal after exclusive creation, and regular-file or symlink replacement before SQLite opens. These checks do **not** make filesystem initialization atomic: a privileged or same-user actor who can mutate the containing directory can still replace the path between observations or after the final check. The storage directory must be service-owned and inaccessible to untrusted writers; independently anchored checkpoints, authenticated broker reconciliation, verified crash recovery, and per-order owner approval remain mandatory before any real-order integration. No broker API, execution path, credentials, or deployment is introduced.


## POSIX storage boundary and process-death quarantine (27 October 2026)

Ledger creation, inspection and transitions now **fail closed** unless the immediate containing directory is owned by the effective service user and private to that user (no group/other permissions; typically mode `0700`). Symlinks in the directory path are rejected. The ledger itself must be a regular file owned by the effective service user, with exactly mode `0600` and one hardlink. A file chmod, extra hardlink or relaxed parent permissions must block **both reads and writes**, without silently fixing ownership or modes. Initialization verifies these conditions before and after the SQLite connection, and connection opening compares the parent directory's device/inode before and after SQLite opens. Platforms without POSIX owner/mode enforcement are deliberately unsupported by this local evidence implementation.

This protects against accidentally world-readable intent evidence, hostile SQLite sidecar placement and some pathname redirections. It does **not** defend against a malicious process running as the same service user, all filesystem swaps after opening, mount manipulation, an attacker with root privileges, untrusted ancestors with mutable directory entries, or rollback of an unanchored database. Use an isolated, service-owned private directory on durable storage, independently trusted audit checkpoints, and authenticated broker reconciliation. These checks are not a substitute for order-specific owner approval or an actual execution safety gate.

Additional synthetic tests reject nonprivate file modes, hardlinked files, public or symlinked parent directories, parent replacement during SQLite opening and unexpected permission relaxation. An actual subprocess is terminated immediately after the `ATTEMPT_UNKNOWN` commit to verify the irreversible quarantine survives process death. These tests remain offline and submit no orders.

The `inspect_ledger` diagnostic now includes `last_recorded_at_ms` (an audited integer for populated ledgers, `null` for an empty ledger). The external checkpoint fence uses it to reject an event timestamp later than its independently trusted checkpoint time. Ledger event timestamps are still caller declarations; they do not independently authenticate a clock or broker event.


## WAL/SHM evidence quarantine (27 October 2026)

The offline submission-attempt ledger is deliberately restricted to SQLite's
**DELETE rollback-journal mode**. Opening a database with an unexpected journal
mode now fails closed rather than silently changing its mode. Existing
`-wal` and `-shm` sidecars (including dangling symlinks) are rejected
before and immediately after SQLite opens the ledger; one-time initialization
also refuses orphaned sidecars. The connection sets
`PRAGMA trusted_schema=OFF` before auditing the reviewed DDL. No sidecar is
deleted, checkpointed, migrated, repaired or treated as authenticated broker
evidence. Synthetic tests cover unreviewed sidecars, symlink sidecars, orphaned
initialization and persisted WAL-mode headers on read and write paths.

**Why:** SQLite WAL files may contain committed transactions not yet
checkpointed into the main database file. Accepting an unexpected WAL/SHM
state would complicate audit recovery and allow a different durability model
than the reviewed rollback-journal path. This restriction is an intentional
availability trade-off, not a claim that WAL itself is unsafe. An ordinary
rollback `-journal` may still be needed for crash recovery and is not
automatically removed. These pathname checks remain vulnerable to privileged
or same-user replacement races, and do not authenticate broker inventory,
owner approval, or externally trusted audit anchors. Do not enable broker
execution based on this ledger.


## Rollback-journal path quarantine (27 October 2026)

SQLite DELETE-mode rollback journals can be necessary for **recovering an interrupted transaction**. The ledger therefore does not delete, truncate or automatically reject an ordinary regular `-journal` file. However, an attacker-controlled symlink, hardlink, directory, special file, foreign-owned file or oversized journal could redirect SQLite reads/writes or cause unexpected resource consumption. Before opening a ledger, immediately after SQLite opens it, and before one-time initialization, the connector now inspects the `-journal` pathname with `lstat`. If present, it must be a regular file owned by the service user, have exactly one hardlink and be no larger than twice the reviewed ledger byte limit. Unsafe paths fail closed without cleanup or automatic repair. A rollback journal with group/other **write** bits is now also rejected (e.g. `0666` or `0620`); ordinary SQLite `0644` journals are permitted because the service-owned parent directory is private (`0700`). This is defense in depth against unsafe sidecar permissions, not an atomic defense against same-user or privileged path replacement. The parent directory remains required to be service-owned and private.

Synthetic tests exercise symlink, hardlink, directory and oversized journal rejection for read and write entry points, orphaned journal initialization, a journal swapped in during SQLite opening, and ordinary empty-journal inspection. The existing abrupt-process-death rollback regression is retained to verify real crash recovery. A same-user or privileged attacker with directory write access can still swap journal paths between checks; these are **not** atomic openat/O_NOFOLLOW protections. Journal bytes are not authenticated broker evidence. Keep the ledger offline, draft and undeployed pending independently verified production restore/rollback/health gates and broker-specific reconciliation.


## Mid-operation storage identity fence (27 October 2026)

Opening a verified SQLite file does not guarantee that its pathname, private
permissions, parent directory or journal remain unchanged during a potentially
long audit or transaction. Both read-only inspection and transitions now
capture a fresh storage fingerprint (parent device/inode and ledger device/inode)
after opening, and recheck the private parent, 0600 ledger permissions, file
size, WAL/SHM absence and rollback-journal safety after audit replay. Writes
also recheck before and immediately after commit; reads recheck after their
transaction ends. A mismatch or unsafe sidecar **fails closed**. Six synthetic
regressions inject mid-audit regular-file replacement, permission relaxation,
or an unsafe journal symlink for both read and write paths.

These are **best-effort pathname observations**, not an atomic fd-to-path
binding, a cryptographically anchored audit, or a defense against same-user or
privileged actors swapping files between checks. If an attacker replaces a
journal during a write or after the final check, this guard cannot guarantee
safe SQLite rollback or commit. A post-commit mismatch cannot undo a commit
that already occurred, so the caller must quarantine the outcome and reconcile
independently. Do not integrate an order sender until storage ownership,
authenticated broker inventory, crash-point recovery and independent audit
anchors are verified. No execution permission is introduced.
