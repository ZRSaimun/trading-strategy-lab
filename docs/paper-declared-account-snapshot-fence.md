# Offline account/quote freshness and revision fence

`inspect_declared_account_snapshot_fence(account, risk_quote, current_snapshot, previous_snapshot, policy, now_ms)` is an isolated, **caller-declared** diagnostic for future integration with the order-risk preview and quote-to-risk binding. It does not connect to a broker, persist state, place orders, reserve funds, validate credentials or approve paper/live execution.

It checks exact typed equality between the risk account/quote used by the preview and those declared in the snapshot. It also checks account observation/receipt chronology, account transport delay, account/quote observation skew, positions/orders sync freshness, unresolved submission attempts, reconciliation completeness, broker/account identity and session/revision/timestamp rollback relative to an optional previous snapshot. Session changes always require external reconciliation. The policy is constrained to **at most 3 seconds** for account and inventory freshness, **1 second** for account transport and quote/account skew; these are diagnostic ceilings, not guarantees or broker-specific entitlements.

Malformed schemas, malformed decimal-string balances or prices, unsupported broker labels, crossed quotes, bool/int confusion in integer fields, unsafe policy ceilings and invalid counters raise `ValueError`. A declared open account circuit breaker produces a HOLD. Unsafe declared chronology or reconciliation produces `HOLD_ACCOUNT_SNAPSHOT_REVIEW`. Matching declared evidence produces only `DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED`. Every result has `may_submit_paper_order=false`, `may_submit_real_order=false`, `broker_authenticated=false`, `account_authenticated=false`, `quote_authenticated=false`, `external_reconciliation_verified=false` and `atomic_reservation_verified=false`. No loss cap or stop fill is guaranteed.

**Trust boundary:** A caller can fabricate, reorder or replay both snapshots. A missing prior snapshot does not prove monotonicity. A production broker adapter must obtain independently authenticated account/position/order evidence, preserve durable replay state, reconcile UNKNOWN submissions and pending stops, bind a transactionally consistent risk reservation to a current quote, and require explicit positive owner confirmation for each specific live order. Trading 212's public API documents Invest/Stocks ISA support, not CFD execution. Do not merge/deploy without full exact-head CI and independently verified production backup restoration, rollback and authenticated health checks. No profitability guarantee.


## Fresh-looking rollback quarantine (29 October 2026)

Within the same declared broker session, a newly observed account envelope
cannot silently carry **older** positions or orders sync timestamps than its
previous snapshot. Likewise, for the same primary instrument and quote source,
a backward observation or receipt timestamp is a HOLD even if the quote is
still within the configured freshness window. This closes a gap where an
increased account revision and a fresh envelope could mask replayed inventory
or quote evidence. Unchanged timestamps remain acceptable while still fresh:
an unchanged inventory or reused quote does not automatically imply rollback.

Failures are `positions_sync_time_rollback`,
`orders_sync_time_rollback`, `quote_observation_time_rollback`, or
`quote_receipt_time_rollback`; the composed account/quote/order diagnostic
also propagates these holds. Session rollover already requires external
reconciliation. These checks are **not** durable anti-replay protection:
caller-declared snapshots can be fabricated together, and real broker data
requires authenticated, persisted, source-bound monotonic checkpoints before
any atomic risk reservation. Neither a clean diagnostic nor a fresh quote
authorizes a paper or real-money order.
