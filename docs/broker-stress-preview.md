# Gap, margin and leverage stress preview (research only)

The owner-authenticated private API has an additional optional **POST /api/broker/stress-preview** endpoint. It extends the existing risk preview and **does not place any order**, connect to a broker, store a credential, or write to a database.

Required JSON fields are the existing `/api/broker/order-risk-preview` fields plus:

- `stressed_exit_price`: a user-chosen hypothetical worse fill than the protective stop (below the stop for BUY; above it for SELL).
- `margin_requirement_percent`: a hypothetical percentage of notional required as initial margin (greater than 0, at most 100).
- `max_leverage`: a hypothetical user-selected exposure/equity limit (greater than 0, at most 100).

The service computes stressed P&L using `abs(entry - stressed_exit) * quantity * point_value + estimated_total_cost`. It compares the unrounded stressed loss with the cash risk budget, estimates required margin as `notional * margin_requirement_percent / 100`, and compares effective leverage `notional / account_equity` against the selected cap. The existing nominal stop-risk result remains separately available. All four illustrative gates (normal risk, stressed risk, margin coverage, leverage) must pass for `all_hypothetical_limits_pass` to be true. This flag **does not authorize an order**. `may_execute_real_order` and `may_execute_paper_order` remain false regardless of result.

## Limitations

The numerical engine also fails closed if positive input values overflow or underflow IEEE-754 calculations, including a finite loss divided by near-zero equity. It rejects misleading zero computed exposure/loss/budget and non-finite risk percentages with HTTP 422 rather than returning an invalid JSON `Infinity` or an apparent pass. This is arithmetic validation, **not** a verified broker risk limit.\n\nThe stressed fill is **one user-supplied scenario, not a maximum possible loss**. Real fills may be worse due to gaps, price limits, outages, spreads, financing, borrow, currency conversion and partial execution. Stop orders are not guaranteed. The estimated margin percentage is not broker-verified, is not a liquidation threshold, and is not a replacement for actual CFD contract and margin schedules. `point_value` and account-currency conversion must be independently verified. Historical bid-only data cannot establish executable ask prices. There is no broker connectivity or automatic risk limit enforcement at order entry.

For CFD accounts, do not assume the Trading 212 Public API supports CFD execution. Its published [API documentation](https://docs.trading212.com/api) describes Invest/Stocks ISA, not CFD orders (checked 24 October 2026).

## Verification

Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_broker_stress.py tests/test_broker_readiness.py`. These tests cover nominal-versus-gap loss, independent leverage/margin failure, both directions, malformed inputs, numerical overflow/underflow, JSON-safe 422 failures, owner authentication and absence of an order endpoint.

Do not merge or deploy this branch until complete CI and production rollback/health checks have been independently verified.
