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


## Same-observation price and primary-feed continuity (29 October 2026)

A later declared account revision cannot make a **same-source, same-instrument**
quote with an unchanged observation timestamp carry a different bid or ask.
That produces `quote_payload_changed_without_new_observation`. Reusing
an identical, still-fresh quote remains permitted; a changed price with a
genuinely later declared observation timestamp is not rejected by this
particular check.

A change of declared primary quote source for the **same instrument** in the
same declared session produces
`quote_source_change_requires_external_evidence`, even if the new feed's
timestamps appear fresh. This deliberately prevents a source-label switch
from bypassing source-bound replay checks. A production implementation needs
independently authenticated source transition and durable quote checkpoints
before releasing such a hold; this diagnostic has no release mechanism.
Different instruments are not automatically treated as a feed switch.

Both failures propagate through the composite account/quote/order diagnostic.
They are **caller-declared, read-only heuristics**, not proof of actual
market-data authenticity, a stop-fill guarantee or permission to submit an
order. A caller can forge both snapshots; never use these checks as a
substitute for authenticated broker evidence or atomic risk reservations.


## Standalone safety-release and inventory-revision continuity (29 October 2026)

The standalone snapshot fence now rejects a declared transition from an open
circuit breaker to closed, a reduction in unresolved submission attempts, or
a transition from incomplete to complete reconciliation. Each requires
independent external evidence; advancing the declared account revision or
starting a new session does not itself release these safety holds.

Within the same declared session, changes to `open_notional` or `open_risk`
without an increased positions revision, and changes to the unresolved attempt
count without an increased orders revision, also cause a HOLD. These checks
previously existed in the composed account/quote/order review; they now apply
to direct callers of the standalone fence as defense in depth. The composite
continues to enforce its own independent checks.

Failure names are
`circuit_breaker_reset_requires_external_evidence`,
`unknown_attempt_reduction_requires_external_evidence`,
`reconciliation_release_requires_external_evidence`,
`positions_changed_without_revision`, and
`unknown_attempts_changed_without_orders_revision`.

These are deliberately conservative **caller-declared diagnostics**, not
authenticated account statements, external release receipts, durable
checkpoints, or broker permissions. Legitimate resets, reconciliation, and
position/order updates can remain quarantined until independently verified.
Every result continues to prohibit paper and real order submission, and live
orders always require separately recorded owner approval and secure broker
credentials. Do not infer a guaranteed stop fill, margin availability or
profitable trading from a clean diagnostic.
