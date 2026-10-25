# Offline paper valuation freshness gate (Loop 5)

`auditPaperValuationFreshness(events, source, policy, asOf, maxValuationAgeSeconds)`
replays the disconnected paper journal and distinguishes a **last observed** mark
from an **as-of** research valuation. For an open paper position, an old quote
forces `STALE_OPEN_MARK` and returns `null` for as-of equity and unrealized P&L.
A flat portfolio can show its realized cash balance without a market quote.
The boundary is inclusive; the default maximum age is 120 seconds, and the
policy may not exceed 3600 seconds.

All quotes, receipt timestamps, and `asOf` are **caller supplied and
unauthenticated**. Even `RECENT_UNAUTHENTICATED_MARK` is NOT a live or executable
quote, verified paper fill, current broker balance, trade recommendation, or
permission to send notifications or orders. `lastObservedEquity` and observed
peak-to-trough drawdown are historical journal diagnostics, not current risk
estimates. An unobserved gap, overnight carry, financing, commissions or
adverse price move can increase real losses beyond the displayed history.

Run synthetic tests with Node 22:

```sh
cd frontend
node --experimental-strip-types --test tests/paper-valuation-freshness.test.ts
npm run typecheck
```

**No deployment/activation:** No provider API, persistence, transaction, broker,
notification transport or live execution is connected. Keep PR #27 draft until
main reconciliation, exact-head green CI and owner-confirmed Render production
backup/restore, rollback and health checks.

**Loop 1 handoff:** Supply licensed authenticated *prospective* two-sided quotes,
server-owned immutable receipt times, session/expiry and stale-data semantics,
transactional append-only quote/order journal, and concurrent worker recovery.
Historical BID candles cannot supply an executable ask or prove spread/slippage.
Each real-money order still requires eligible documented broker API, scoped
credentials, hard limits and separate owner confirmation for that order.
