# Replay-verifiable paper journal and atomic persistence contract

This experimental module extends the independent quote-driven paper execution engine in PR #18. It is **not** connected to a broker, historical market feed, database, API route or production UI.

## What is implemented

- PaperReplayJournal records accepted paper submissions, cancellations and *all* accepted quote events, including quotes that caused no fill. Invalid events are never appended. Exact instrument/provider/venue and price-side identity remains isolated.
- The bounded JSON checkpoint contains source identity, versioned ordered actions, derived orders and state-change history. Restoring it replays every event through the original deterministic paper ledger and rejects mismatched order P&L, missing/reordered actions, extra fields and invalid chronology.
- PersistentPaperSession exposes an async PaperCheckpointStore contract. A caller must implement a **durable atomic compare-and-swap** operation for revisions. Each new event is applied to an isolated replay candidate, then saved through CAS **before** the in-memory session publishes the change. A save failure or competing writer leaves the session unchanged; callers must reload after a conflict.
- Maximum checkpoint length is 8,000,000 JSON characters and at most 50,000 actions. This is a bounded research prototype; replaying the full history on each event is deliberately simple but expensive and is not a production-grade streaming architecture.

## What this does NOT establish

The included tests use an **in-memory fake CAS store**, which simulates restart and write conflicts. No PostgreSQL, IndexedDB or external durable adapter has been deployed or verified. Actual crash-safe persistence requires an atomic transactional database implementation, database backups, retention, access controls, and restart/recovery integration. A fake CAS implementation that reads then writes without a transaction is unsafe.

Deterministic replay detects inconsistencies against the stored actions; it **does not cryptographically authenticate** a maliciously rewritten log and expected outcomes. A real deployment needs authenticated, append-only event provenance, an integrity hash/signature chain anchored outside the mutable database, and quote-source verification. This module neither verifies executable bid/ask liquidity nor supports broker fills, withdrawals or live orders. Paper profitability is unproven.

## Verification

From the frontend directory:

    node --experimental-strip-types --test tests/paper-replay-journal.test.ts
    tsc --noEmit --lib es2022,dom --target es2022 --module nodenext --moduleResolution nodenext --allowImportingTsExtensions lib/paper-replay-journal.ts

Eight deterministic tests cover chronological replay, idempotent order IDs, corruption/missing events, rejected invalid quotes, restart continuation, CAS conflicts and failed writes. All eight passed locally on Node 22 with a local copy of the current paper engine; the isolated TypeScript check passed. Full backend/frontend/Docker/cloud CI must be checked on the **latest PR head** before merge.

## Handoff

1. Build an authenticated, source-isolated PostgreSQL adapter with a unique session identity, atomic compare-and-swap revisions, encrypted backups and restore drills. Prevent unbounded database growth and implement periodic integrity-checked checkpoints without losing original actions.
2. Add crash/retry and two-process concurrency integration tests, including an interrupted transaction. Keep any missing/failed event **unsettled** rather than inventing a paper fill.
3. Only then wire the private UI to clearly labelled DEMO/PAPER orders and owner-authorized live bid/ask quote sources. Compare with real demo-broker statements and recorded financing/margin terms before interpreting simulated P&L.
4. Real-money execution remains separate, requiring a supported broker API, hard server-side limits, fresh executable quotes and explicit owner confirmation per specific order.
