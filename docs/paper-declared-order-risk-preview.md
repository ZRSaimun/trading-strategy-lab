# Disconnected order risk preview (not trade authorization)

`app.paper_declared_order_risk_preview.inspect_declared_order_risk_preview` is an **offline, read-only, caller-declared** preflight. It does not fetch broker data, create orders, reserve margin, execute stops, contact a CFD broker, persist an audit log or authorize demo/live trading. A clean result is `DECLARED_RISK_PREVIEW_UNVERIFIED` and **both** submission flags remain false. An unsafe result is `HOLD_RISK_REVIEW`; malformed inputs raise `ValueError`. The owner must separately approve **each specific live order** after authenticated account and quote checks. Do not wire this output directly into execution.

Exact-schema decimal-string inputs cover quote bid/ask, quote age and transport lag, spread, stop direction, conservative stop-distance plus slippage-buffer loss, position and portfolio risk, daily loss, gross notional, requested leverage, free margin, order size, duplicate IDs/fingerprints and order-rate limits. Bounds prevent permissive policies. Stop-distance plus a slippage allowance is **not a guaranteed maximum loss**: gaps, financing, commissions, currency conversion, failed stops and broker outages can exceed the estimate. Prices and equity must be in compatible quote/account currency units; this offline helper does not perform FX conversion, contract-multiplier conversion or broker-specific margin calculations. Do not use it for derivatives or CFDs without those verified conversions and instrument specifications.

The `recent_orders` list is caller-supplied, not durable or atomic. A clean local calculation cannot stop concurrent workers, replay after restart, authenticate quote freshness, establish actual margin or enforce a live circuit breaker. Future integration requires provider-authenticated quotes and positions, durable unique intent keys, transactional risk reservations, broker-supported stop placement/verification, independently retained audit evidence, read-only reconciliation of UNKNOWN attempts (PR #148/#152), explicit per-order human review, and production rollback/health gates. Trading 212's public API does not support CFDs. No real-money order was submitted.

## Cash-account broker boundary (29 October 2026)

For the four supported `T212-INVEST-*` / `T212-STOCKSISA-*` labels, the
preview now places a `HOLD_RISK_REVIEW` when the requested leverage differs
from exactly 1×, when the declared maximum-leverage policy differs from 1×,
or when the order is a SELL without independently authenticated owned
holdings. This is a conservative **cash securities** constraint: a SELL may
be a valid disposal of owned shares, but this disconnected preflight has no
trusted holdings inventory, so it must not infer sellability or shorting
permission. `PAPER-LOCAL` retains its bounded hypothetical leverage and
short-side simulation; that is **not** a real broker capability.

A clean cash BUY diagnostic is **not** a broker instrument-entitlement check,
a cash balance reservation, an order authorization or proof of Trading 212
account availability. The test ticker is deliberately synthetic. The official
Trading 212 Public API documents Invest and Stocks ISA support, not CFD
execution: https://docs.trading212.com/api/section/general-information/api-limitations .
No CFD endpoint, credentials or broker network request is implemented here.
