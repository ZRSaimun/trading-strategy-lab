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
