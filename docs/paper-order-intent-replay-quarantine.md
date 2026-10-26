# Loop 4 — durable paper order-intent replay quarantine (25 October 2026)

This is a **disconnected, opt-in PAPER research safety component**. It neither sends nor authorizes demo/live orders. There is no HTTP route, broker SDK, key storage, network request, real-money order, or automated approval. No database migration is needed: the existing `Record` and `Audit` tables are used. Do not treat this module as a complete broker idempotency solution.

## Design

- `PaperOrderIntentRegistry.register` writes a one-use client-order alias, account alias, SHA-256 review fingerprint, server-supplied creation time, short expiry and `PREVIEW_ONLY` state. Aliases are hashed before storage/audit. Fingerprints are *not* signatures or authenticated owner consent.
- The database primary-key uniqueness prevents duplicate registration, including after restarts, changed fingerprints, expiry and attempted retries. Different account aliases have separate namespaces. There is deliberately no pruning, reactivation, ID reuse, or release endpoint.
- `mark_outcome_unknown` is an explicit CAS transition to permanent `OUTCOME_UNKNOWN`. It is for recording a potentially ambiguous future order outcome; it never retries, cancels, fills or submits an order. A separate authenticated broker reconciliation process must be designed before any terminal state could be recorded.
- Each successful write and its audit event commit in one transaction; failures roll back together. `load` validates the full stored envelope, exact types, state transitions, timestamps, duplicate JSON keys and checksum. SHA-256 here detects accidental corruption, **not malicious database tampering**. A missing/corrupt/stale record never grants execution permission.
- Both `may_execute_paper_order` and `may_execute_real_order` are **always false**. The registry has no execution capability.

## Test

From `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_paper_order_intent_registry.py
```

The synthetic SQLite regression suite exercises duplicate/restarted IDs, cross-account isolation, fingerprint mismatch, unknown-outcome quarantine, invalid metadata, corrupted records, redacted identifiers, atomic audit rollback, and concurrent duplicate registration. Persisted intent envelopes larger than **16 KiB UTF-8** now fail closed **before JSON parsing** (including on quarantine attempts); the existing small canonical envelope format is unchanged.

**Disposable PostgreSQL acceptance (CI):** the existing `postgres-risk-acceptance` job runs `backend/tests/test_paper_daily_loss_postgres.py`, now covering the intent registry as well as the daily-loss latch. Three added cases verify concurrent duplicate registration (one winner, one audit), competing unknown-outcome CAS transitions (one winner, one quarantine audit), and atomic rollback on an injected audit insert failure for both transitions. The fixture refuses non-loopback databases and database names not ending in `_test`, then creates/drops a random schema. To run locally, set `TSL_PG_RISK_TEST_URL` to an explicitly disposable local PostgreSQL database; **never use production credentials**. Without that variable the PostgreSQL tests skip. These tests do not simulate process termination mid-commit or prove broker execution exactly once.

## Production integration gates (NOT complete)

1. Verify exact account/provider/venue and server-side credentials without logging or exposing them. Require fresh authenticated bid/ask and broker positions, actual equity/margin, currency/contract specifications, session calendar and order state. Do not use caller-provided `now_ms` or fingerprints as trust evidence.
2. Atomically coordinate the journal, persistent risk reservation (#26), daily-loss latch (#39), position sizing (#35), stop monitor (#36) and immutable owner-reviewed preview (#38). This isolated registry does **not** implement that multi-record transaction or account-wide duplicate suppression.
3. Commit the unknown-outcome quarantine **before** any future external order attempt, and reconcile all uncertain outcomes using authenticated provider order history before considering further action. Even that sequence alone cannot make a non-idempotent provider endpoint exactly-once; do not auto-retry after network timeouts. Design failure recovery, authenticated reconciliation and rate limits first.
4. Require an authenticated, order-specific, time-limited **positive human confirmation** and a separate secure provider credential for every live order; do not equate a SHA-256 fingerprint, `owner_reviewed=True`, or preview checks with consent. Live execution remains disabled.
5. Before any merge/deployment, require latest-head full CI, PostgreSQL concurrency/rollback tests, review of PR overlap, owner-identified production Render workspace, tested backup and rollback, and post-deployment `/health` verification. No paid service or production data migration was used for this change.

## Broker compatibility check

Trading 212's [official Public API](https://docs.trading212.com/api) is beta and supports **Invest and Stocks ISA**, including a demo endpoint, **not CFD accounts**. Its [limit order endpoint](https://docs.trading212.com/api/orders/placelimitorder) explicitly warns that it is not idempotent: identical repeated requests may create multiple orders. This registry is a local defense-in-depth prototype, not an API-side idempotency key and not evidence that Trading 212 CFD can be traded by API.

No strategy profitability or operational broker connectivity is established by these tests.
