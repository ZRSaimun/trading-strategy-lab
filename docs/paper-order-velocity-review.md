# Loop 4 — disconnected paper order-velocity and churn review

`backend/app/paper_order_velocity_guard.py` implements a strict, **read-only** synthetic attempt-rate evaluator. It does not authenticate a broker, create orders, reserve funds, mutate a journal, record consent, or allow demo/live execution. Both execution flags are always false. The SHA-256 fingerprint is an audit diagnostic, not an approval signature.

The caller declares a bounded, timestamped 24-hour history of **attempts** (including rejected, canceled, pending and unknown-outcome attempts), an account-specific candidate and a safety policy. The evaluator fails closed for stale/incomplete snapshots, sequence gaps, duplicate IDs or intents, recent same-symbol attempts, too many hourly/symbol/UTC-day attempts, repeated direction flips, uncertain outcomes, and emergency/daily-loss circuit breakers. Strict field schemas reject unexpected data (including accidental secrets), booleans as numbers, oversized histories and malformed fingerprints.

The UTC day is computed from the trusted server clock, not a browser timezone. Rolling hourly and 24-hour checks use the same server clock. Attempts count even if the broker rejected them, preventing rejection storms from bypassing the intended throttle. An unresolved or cancellation-pending outcome forces reconciliation rather than retry. Historical order state and event population remain **caller-declared and unauthenticated**; the function cannot establish that omitted events do not exist, and a contiguous sequence alone is not proof of completeness.

Test locally from `backend` with `PYTHONPATH=. python -m pytest -q tests/test_paper_order_velocity_guard.py` (synthetic data only).

## Integration gates

1. Persist **every attempted order** and its immutable account/order/intent identity in a transactionally consistent PostgreSQL journal; derive policy, history and server clock from authenticated server-side state. Never trust client-provided coverage claims.
2. Combine with durable reservation/kill-switch state, authenticated broker inventory and quotes, stop acknowledgements, and terminal-order reconciliation. A non-idempotent provider endpoint must not be blindly retried after a timeout.
3. Recheck policy and risk after a human approves a single specific order and immediately before any future supported-provider submission. An authenticated, short-lived, one-time approval and secure credentials are separate prerequisites. This module deliberately does not implement them.
4. Verify PostgreSQL multi-worker races, crash recovery, immutable audit logging, backup restoration, deployment rollback and health checks before enabling any execution path.

Trading 212's published API documents Invest and Stocks ISA account access, not CFD account order execution. No profitability is claimed or implied. Stop orders can gap beyond declared limits.
