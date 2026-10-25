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
