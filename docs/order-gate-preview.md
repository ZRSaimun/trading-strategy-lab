# Quote, duplicate-order and circuit-breaker preview (research only)

The owner-authenticated `POST /api/broker/order-gate-preview` is a **stateless diagnostic**. It accepts a nested `risk` object using the existing stress-preview schema and a `controls` object containing owner-declared bid/ask quote, exact provider/venue/instrument identity, observed/received timestamps in **UTC epoch milliseconds**, client-order ID, a list of prior IDs, open/pending-order flag, kill switch, market session, realized daily P&L, loss-streak cap and explicit owner-confirmation flag.

The backend uses **its own current clock** to check quote age and transport delay. It rejects crossed/zero/overflowed spreads, mismatched instruments, unreasonably wide spreads, stale/future/late quotes, previously seen client IDs, outstanding orders, kill switch activation, market closures, daily loss/streak caps and missing owner confirmation. It also requires the hypothetical entry not to be more favorable than the supplied bid/ask and all existing stressed loss/margin/leverage assumptions to pass. Trading 212 CFD is marked unsupported by its documented public trading API.

## Critical limitations

**This is not a real order gate or a broker connection.** All quotes, balances, P&L, provider names, existing-order flags, client IDs, market-open status and confirmations are **user declarations**, not authenticated provider/account data. The function does not persist anything, atomically reserve IDs, enforce a kill switch across workers or restarts, or submit a demo/live order. An apparently passing preview is not execution permission. Responses always include `may_execute_real_order=false`, `may_execute_paper_order=false`, `quote_authenticated=false` and `durable_circuit_breaker=false`. No account key or secret is accepted.

The preview only supports positive bid/ask prices. It does not model negative-price contracts, partial fills, account currency conversion, exchange halts, CFD financing, margin calls, order-book depth or broker liquidation. A protective stop does not guarantee a loss limit. There is no profitable trading strategy claim.

## Tests and next integration

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_order_gate.py tests/test_order_gate_api.py tests/test_broker_stress.py
```

Before using this logic in paper execution, integrate a source-authenticated quote adapter and **transactional durable order-ID reservations** with restart-safe account-wide kill-switch and P&L state. Verify provider-specific bid/ask and exact instrument contract details; then compare against authorized demo broker fills. Do not enable real-money execution without eligible official broker API, scoped credentials, hard limits, and explicit confirmation of each proposed order.

This feature is additive to PR #14. PR #18 owns the separate in-memory paper ledger; avoid editing its files or assuming this preview provides the persistence missing from that ledger. Do not merge to production until the Render workspace, backups, rollback and all latest-head CI jobs are verified.
