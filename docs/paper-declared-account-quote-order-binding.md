# Offline account–quote–order binding

`inspect_declared_account_quote_order_binding(order, risk_quote, account, risk_policy, recent_orders, primary_source, quote_sources, consensus_policy, current_snapshot, previous_snapshot, snapshot_policy, now_ms)` composes the existing disconnected order-risk, multi-feed quote and account-snapshot diagnostics. It performs no network I/O, state mutation, order reservation, brokerage connection or execution.

## Safety checks

- Reuses the underlying strict schema, arithmetic, quote-consensus and account freshness/revision checks; propagates their HOLD results without suppressing details.
- Requires a declared previous account snapshot. Missing history is a HOLD, not proof of a new account session.
- Holds when a prior open circuit breaker becomes closed, unresolved attempts decrease, or incomplete reconciliation becomes complete without independently authenticated external evidence.
- Detects position exposure changes without a positions revision and changes in unresolved attempts without an orders revision in the same session.
- Holds when declared account age, transport delay, quote/account skew or positions/orders synchronization ceilings are weaker than the paired risk/quote/account limits.
- Rejects malformed inputs via the underlying validators. It does not mutate caller data.

A clean declared result is `DECLARED_ACCOUNT_QUOTE_ORDER_UNVERIFIED`. Any suspect condition produces `HOLD_ACCOUNT_QUOTE_ORDER_BINDING`. **Neither is a trading authorization.** All authentication, independence, reconciliation, atomic reservation, stop guarantee, and paper/live submission flags are false. Individual positive owner approval is required for each specific live order, in addition to separate authenticated provider credentials and production risk gates.

## Trust boundary and release

All evidence is supplied by the caller and can be forged, replayed or selectively omitted. In particular, a previous snapshot may be fabricated, so passing revision continuity is not durable proof. The estimated stop loss is not a guaranteed maximum loss during gaps, financing, currency conversion, broker outages or slippage. CFD eligibility must be checked per provider, account, region and instrument; Trading 212 Public API documentation does not cover CFD accounts.

**Do not merge or deploy** until exact-head CI is green, the related durable ledger and provider evidence are independently reconciled, and backup restoration, rollback rehearsal, release impact and authenticated health checks are verified. This is a diagnostic building block, not a replacement for transactional risk reservations, broker stop confirmation, or a human-reviewed live-order preview.
