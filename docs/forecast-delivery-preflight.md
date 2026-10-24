# Offline forecast delivery claim preflight (Loop 5)

`frontend/lib/forecast-delivery-preflight.ts` adds a pure read-only preflight
over the existing source-isolated delivery journal. It does not create a claim,
write to a database, send a notification, fetch a quote, or trade.

Given a self-attested journal, a caller-supplied epoch-second `asOf`, and
explicit limits, it replays the journal and classifies each review candidate:

- **REHEARSAL_ONLY**: pending, within the candidate target-close age budget,
  below the attempt limit and outside the post-release cooldown.
- **BLOCKED**: stale, cooldown active, attempts exhausted, cancelled, a
  self-attested ACK recorded, or an in-flight claim needing reconciliation.

The stale age is measured from `latestTargetClose`, **not** queue creation
time, to prevent delayed queuing from refreshing obsolete alerts. The age
boundary is inclusive. In-flight events always block retries even after the
age budget expires. Self-attested ACK is not proof of external delivery.

This is a safety-oriented **offline rehearsal** and is deliberately not an
operational dispatcher. Its `claimIsAtomic=false`, `transportConnected=false`,
and `live=false` flags are unconditional. The caller's `asOf` is not an
authenticated server timestamp. Replay can be rewritten, and two workers
could make the same rehearsal decision. Do not use its result to authorize a
send, claim or order.

## Operational prerequisites (Loop 1 / future Loop 5)

1. Licensed, authenticated completed-candle feed with source, price-side,
   session-calendar, delay and trusted receipt-time evidence.
2. Transactional append-only event/outbox storage with unique candidate and
   attempt constraints, compare-and-swap claim leases, and crash/two-worker
   tests. Release only after independently authenticated delivery reconciliation.
3. Real notification transport with authenticated receipts and expiry policy,
   idempotency, backoff and bounded delivery budgets; explicit user opt-in.
4. Independent forward paper ledger and executable bid/ask simulation with
   spread, slippage, financing and margin/downside-risk reporting.
5. Any real broker order requires a supported eligible account, valid current
   executable quote, risk checks and explicit owner confirmation for **each**
   order. This module contains no broker integration or execution route.

Tests use synthetic candidates and timestamps only. No verified forward
performance, net return, drawdown, or live alert-delivery rate is implied.
