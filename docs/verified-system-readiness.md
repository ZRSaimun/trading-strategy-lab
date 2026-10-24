# Verified system readiness (no broker orders)

The authenticated **Broker Readiness** screen now requests
\`GET /api/system/readiness\`, a read-only, owner-session-protected endpoint.
This is a verification checklist and release gate, **not** proof of a
profitable strategy or an automated trading feature.

## Checks

- Number of rows in legacy server chart storage (historical observations)
- Number of READY source-isolated historical dataset manifests in the *cloud*
- Sum of importer-declared accepted candle counters for READY datasets
- Explicitly unavailable: verified live executable quotes, connected broker,
  prospective unattended paper-trading execution, independently established
  post-cost statistical edge, and live order integration

The READY-manifest counter is a declared import counter, not an independent
full-candle count; the API clearly distinguishes the two.

A 5,000-row legacy chart or the offline 3.78m-candle backup does not satisfy
cloud archive readiness. Historical bid-only candles are not executable
bid/ask quotes or a substitute for account authentication.

When storage tables are unavailable, the endpoint fails closed and reports
RESEARCH_ONLY; it never returns "trading ready" from partial input or error
conditions. No production database row changes, vendor API calls, credentials,
broker API requests or automatic orders are possible through this GET route.

## Next technical milestones

1. Approve a private, resilient storage plan and verify archive licence/rights.
   Import only authorized historical data, with source IDs and reproducible
   checksums. Restore and test backup on staging before bulk cloud migration.
2. Verify exact Gold/NSXUSD/WTI CFD feed mappings, trading hours and real
   timestamped bid/ask quotes via an officially supported provider.
3. Implement persistent paper execution against source-verified quotes and a
   realistic cost model; reconcile and monitor prospective performance.
4. Establish out-of-sample evidence over different market regimes and costs;
   reject strategies with no demonstrated edge or unacceptable drawdown.
5. Obtain documented execution API support for the specific *account type*,
   not just the broker brand. Official Trading 212 API supports Invest and
   Stocks ISA, **not** CFD accounts as of 24 Oct 2026:
   https://docs.trading212.com/api
6. Complete independently verified broker risk gating, emergency stop,
   order idempotency, per-trade owner confirmation, audit and recovery before
   allowing any live order.

This deployment is not equivalent to approving a particular financial
transaction or trading without financial risk.
