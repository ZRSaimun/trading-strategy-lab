# Disconnected broker snapshot replay fence (Loop 4)

`backend/app/paper_broker_snapshot_replay_fence.py` compares two caller-declared
snapshots of one broker account against the same unresolved-order population.
It reruns the bounded inventory census on **both** snapshots, using their
respective trusted-caller observation times. A previous `PARTIAL` or `OPEN`
status is permitted as an unresolved diagnostic; other previous census
failures and **any** current census failure require `HOLD_RECONCILIATION`.

The fence detects reused snapshot IDs, nonincreasing or skipped caller-assigned sequence,
nonincreasing observation/receipt timestamps, account changes, missing orders,
broker-order ID changes, decreasing cumulative filled quantity, disappearance
or mutation of prior fill receipts, and terminal status changes. Legitimate
broker corrections, cancellations after partial fills, split/merged accounts,
provider clock behavior or pagination races may trigger a HOLD requiring
provider-specific human reconciliation. Additionally, the fence holds when the
new snapshot's observation timestamp is at or before the previous snapshot's
receipt timestamp (ambiguous overlapping acquisition), or a newly disclosed
fill is timestamped at or before the previous snapshot's observation time
(retroactive fill / previously incomplete inventory). A newly disclosed
fill timestamped at or before the **prior trusted-caller census check** is
also held, even when it postdates the prior broker observation: that previous
checkpoint was already missing the fill when checked. The boundary is
inclusive. These can be legitimate provider reporting delays, but are **not**
sufficient evidence to release a quarantined order. Boundaries are inclusive; neither clock nor fill receipt is
broker-authenticated. Neither sequence nor snapshots are
provider-authenticated; the caller must independently persist and authenticate
the prior checkpoint. The new observation must also occur strictly after the
previous trusted-caller check time; an earlier/equal observation is held as an
ambiguous or backdated transition. Sequence numbers are required to advance by
exactly one, and a gap is held because intervening snapshots may be missing.
These conservative conditions may reject legitimate delayed ingestion, but
cannot prove provider-side continuity. The function does not persist a checkpoint or call a
broker. `DECLARED_TRANSITION_CANDIDATE_UNVERIFIED` is **not** permission to
clear an `ATTEMPT_UNKNOWN` quarantine or retry a non-idempotent order.

All six authentication, release and paper/live execution flags are always
false. No credentials, network, database migration, order route, paid service
or deployment is added. Integrate only after read-only authenticated provider
receipts, durable order-ledger binding, atomic risk reservations, protective
stop verification, quote freshness and individual signed owner approvals are
independently tested. No CFD API support or profitability is inferred.
