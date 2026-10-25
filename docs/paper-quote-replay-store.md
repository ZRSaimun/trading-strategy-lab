# Durable paper quote replay markers — offline safety component

`backend/app/paper_quote_replay_store.py` persists a bounded per-account/source quote observation marker using existing SQLAlchemy `Record` and `Audit` tables. It is deliberately **disconnected**: no HTTP endpoint, credentials, broker request, paper fill, live order, schema migration or deployment is added. The caller must inject a trusted server clock (`now_ms`); the module cannot authenticate that clock or the claimed broker feed. `ACCEPTED_UNVERIFIED` means **only** that an untrusted observation passed structural tests and its marker was durably written. Both `paper_order_permitted` and `live_order_permitted` are always `false`.

The exact source identity is the owner-declared `{account_alias, provider, venue, instrument}`. Identity and quote IDs are SHA-256 hashed before persistence and audit. These hashes provide partitioning and accidental corruption detection, **not authentication or secrecy against guessing**. The module accepts positive bounded Decimal-string bid/ask values, checks crossed/locked markets, maximum spread in basis points, quote freshness, source timestamp <= receipt <= server time, and transport delay. It requires strictly increasing sequence, observation time and receipt time, monotonic server clock, and rejects the 64 most recently accepted quote identifiers. Older identifiers are not remembered; provider sequence continuity and authenticated transport are required upstream. Out-of-order, stale, malformed, concurrent and corrupt states fail closed; no automatic retry or gap repair occurs.

Successful updates use a unique initial insert or full-value compare-and-swap update in one database transaction with a minimal hashed audit record. An audit insert failure rolls back the marker. A concurrent race returns `HOLD_RECONCILIATION` rather than silently accepting both. This is not yet a durable circuit breaker or a paper journal transaction. **A HOLD must block downstream paper-order eligibility until independently reconciled.** Rejects before persistence do not produce a durable rejection audit event; production ingestion requires authenticated request audit, rate limits and backpressure.

## Local synthetic tests

From `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_paper_quote_replay_store.py
```

Tests cover restarts, exact source isolation, spread/freshness/delay rejection, nonadjacent ID reuse, sequence/time replay, malformed Decimal and clock input, stored corruption, atomic audit rollback and competing first writers. SQLite is not a PostgreSQL concurrency or process-kill guarantee. Add a disposable local PostgreSQL two-connection acceptance suite and independent broker-authenticated quote receipts before connecting this to PR #42 snapshot reconciliation. Coordinate any journal/reservation transaction with PR #26, daily-loss latch #39, order intent quarantine #40, stop monitor #36 and human review #38. All related draft PRs require a conflict/CI review before merging.

**Broker boundary:** Trading 212's documented public API supports Invest and Stocks ISA, not CFD execution (official documentation: https://docs.trading212.com/api). This component does not implement or enable a broker adapter. Real-money execution remains disabled and requires secure provider credentials and explicit owner approval for each exact order. No profitability evidence is produced. Keep draft, unmerged and undeployed until exact-head CI, integration, production workspace, backup, rollback and health gates are satisfied.


## Atomic paper quote + journal checkpoint integration (25 October 2026)

`backend/app/paper_quote_journal_atomic.py` adds an **opt-in**, single-SQL-transaction checkpoint across the existing `paper-quote:` marker and `paper-journal:` checkpoint, with a new `paper-journal-source:` account/source binding. It validates matching provider, venue and instrument; binds each session to one account/source hash; rejects stale, crossed, excessive-spread, replayed and out-of-order quote observations; and requires a journal revision CAS. Successful updates commit the quote marker, journal checkpoint, account binding (first insert only) and a minimal hashed audit entry together. A failed audit insert rolls back all writes. Independent writers may race; unique inserts and full-value CAS must fail closed. It never creates or verifies fills, orders or broker requests, and both execution flags remain false even after a successful checkpoint.

**Important:** This component is disconnected, and no authenticated provider data, broker positions, daily-loss latch, order-intent reservation, risk budget, protective stop or owner-specific order approval is integrated. A recorded checkpoint is **not** an authorization. Existing unbound journals are intentionally held for manual reconciliation; do not auto-migrate or silently adopt them. A trusted server clock and authenticated source must be supplied upstream; SHA-256 hashes are not authentication. Rejected observations currently do not persist a rejection audit, so a future authenticated ingestion boundary needs rate-limited durable denial audit and backpressure.

Test locally from `backend` with `PYTHONPATH=. python -m pytest -q tests/test_paper_quote_journal_atomic.py`. The quote PostgreSQL acceptance workflow also exercises two-connection first-writer and revision races plus rollback on audit interruption. These tests cover transaction safety in isolation, **not** an operational end-to-end trading workflow or a process-kill proof. No database migration or deployment is required for this optional module, and production remains unchanged.


## Bound-journal write isolation (25 October 2026)

When `AtomicPaperQuoteJournalStore.checkpoint` binds a paper-journal session to a
hashed quote source/account, `PaperJournalStore.compare_and_swap` now rejects
standalone writes to that session. Otherwise a second writer could advance
the journal without advancing the quote marker, silently breaking the atomic
checkpoint invariant. The check runs in the journal's database transaction;
unique journal inserts and full-value compare-and-swap continue to arbitrate
racing initial and revision writers. Unbound standalone paper-replay journals
remain supported. Synthetic regression coverage checks that rejected bypasses
leave the quote, journal and audit unchanged.

This prevents one alternate persistence path, **not** a direct database writer
with table privileges, and it does not integrate the reservation, daily-loss,
intent, stop or broker reconciliation PRs. No execution authorization is granted.


### Exclusive atomic quote-source ownership (25 October 2026)

The atomic quote+journal checkpoint now records **both** session-to-source and
source-to-session bindings in the same database transaction. A quote source
(account/provider/venue/instrument) may belong to only one atomic paper journal.
A second journal using that source is quarantined; standalone
`PaperQuoteReplayStore.observe` is denied after the source is bound. This closes
the independent quote-marker advancement path that could otherwise leave the
bound paper journal behind the accepted quote revision. Source-owner inserts,
quote marker changes, journal checkpoint updates and the audit entry commit
or roll back together. Neither function grants permission to trade.

**Compatibility / fail-closed recovery:** Pre-existing bound checkpoints created
before the reverse source binding was introduced do not acquire a fabricated
owner automatically. They return `QUOTE_SOURCE_BINDING_INCOMPLETE` and require
manual offline inspection/reconciliation before any repair. Do not silently
rewrite or delete legacy markers, invent broker confirmations, or use a fresh
session to bypass the hold. The source ownership key is a coordination marker,
**not** a verified broker identity or an authorization token.


### Legacy forward-binding quarantine for standalone quote writers (25 October 2026)

A journal/source can retain its `paper-journal-source:` forward binding
while its `paper-quote-journal-owner:` reverse binding is absent (for
example, an incomplete older checkpoint or damaged metadata). Previously the
standalone `PaperQuoteReplayStore.observe` checked only the reverse marker;
it could therefore advance the quote replay marker while leaving the bound
journal unchanged. The observer now also checks surviving forward bindings
before a quote write and returns `HOLD_RECONCILIATION` with
`QUOTE_SOURCE_BINDING_INCOMPLETE` if it finds an orphan. No quote marker,
journal checkpoint or audit record is changed by the rejection.

SQLite and disposable PostgreSQL regression coverage exercise this
incomplete-ownership case. Unbound independent quote sources remain supported.
The forward-binding lookup is a conservative scan over the existing Record
table; monitor its performance as the number of journal sessions grows, and
replace it with a reviewed indexed ownership model before production-scale
ingestion. This is **not** a full proof against arbitrary database tampering or
an authorization to place orders. Manual offline reconciliation remains
mandatory; do not silently create a reverse owner, bypass the hold, or
enable live execution.
