# Disconnected broker snapshot replay fence (Loop 4)

`backend/app/paper_broker_snapshot_replay_fence.py` compares two caller-declared
snapshots of one broker account against the same unresolved-order population.
It reruns the bounded inventory census on **both** snapshots, using their
respective trusted-caller observation times. A previous `PARTIAL` or `OPEN`
status is permitted as an unresolved diagnostic; other previous census
failures and **any** current census failure require `HOLD_RECONCILIATION`.

The fence detects reused snapshot IDs, nonincreasing caller-assigned sequence,
nonincreasing observation/receipt timestamps, account changes, missing orders,
broker-order ID changes, decreasing cumulative filled quantity, disappearance
or mutation of prior fill receipts, and terminal status changes. Legitimate
broker corrections, cancellations after partial fills, split/merged accounts,
provider clock behavior or pagination races may trigger a HOLD requiring
provider-specific human reconciliation. Neither sequence nor snapshots are
provider-authenticated; the caller must independently persist and authenticate
the prior checkpoint. The function does not persist a checkpoint or call a
broker. `DECLARED_TRANSITION_CANDIDATE_UNVERIFIED` is **not** permission to
clear an `ATTEMPT_UNKNOWN` quarantine or retry a non-idempotent order.

All six authentication, release and paper/live execution flags are always
false. No credentials, network, database migration, order route, paid service
or deployment is added. Integrate only after read-only authenticated provider
receipts, durable order-ledger binding, atomic risk reservations, protective
stop verification, quote freshness and individual signed owner approvals are
independently tested. No CFD API support or profitability is inferred.
