# Broker integration readiness and safe hypothetical risk preview

The owner-authenticated private server exposes:

- `GET /api/broker/capabilities`: real supported capability labels, with no account secrets or connection side effects.
- `POST /api/broker/order-risk-preview`: validates a **hypothetical** direction, symbol, entry, stop, quantity, point value, account equity, assumed costs and user-defined risk budget. Returns illustrative exposure and stop-loss estimate, but `may_execute_real_order` is always `false`.

The terminal includes a **Broker Readiness** screen on the private site. The public GitHub Pages build does not offer the private endpoints.

As of 24 October 2026, the official [Trading 212 Public API](https://docs.trading212.com/api) is **beta**, accessible to **Invest and Stocks ISA** accounts, *not* CFD accounts. It offers demo and real-money endpoints for eligible equity accounts. It does **not** grant permission or technical ability to place XAUUSD/NSXUSD CFD orders.

This implementation does not request or store broker credentials, place market/demo orders, retrieve account balances, infer spreads from historical bid bars, or alter the database. It is strictly a calculator using unverified inputs.

### Requirements before adding any live-trading capability

1. Officially supported broker and account type, lawful use and correct exact instrument identifiers.
2. Secure scoped API credentials managed out of public source, no browser/client exposure.
3. Independently verifiable bid/ask executable quotes, rate limits and market hours.
4. Hard server-side trade-risk limits, reconciliation/idempotency, cancellation, kill switch, alerts and audit trail.
5. Verified paper/demo execution and tests including slippage, disconnection, failures and repeated-order safety.
6. Owner review and positive confirmation of each actual order; no unattended autonomous money movement.

Research results and any apparent profitability do not guarantee future returns. Treat protective stops as contingent orders that might slip during a gap. A CFD contract may differ materially from cash indices, futures, or bid-only OTC archives.