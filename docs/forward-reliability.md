# Loop 5: offline forward forecast reliability diagnostics (24 October 2026)

`frontend/lib/forward-reliability.ts` is a pure **UNVERIFIED_LOCAL_RESEARCH** analysis of already-recorded forward forecast records. It does not connect to a market provider, authenticate source/clock provenance, issue predictions, send alerts, place demo/live orders, or persist anything. Do **not** label historical records as live forward performance. This code is not wired to a production UI.

## Contract and safeguards

- Explicit exact instrument, provider, venue, source ID, bid/ask/mid side, candle seconds, model version, and horizon (1/3/12 candles). Mixed sources and malformed/future-dated records throw; versions and horizons are never pooled.
- Fixed UTC-aligned, non-overlapping horizon phase; last 100 settled observations by default, configurable from 50 to 500. The latest window must be contiguous. Missing or voided outcomes within it fail closed. Pending tail outcomes can be excluded **only before their target candle closes**; overdue unresolved predictions fail closed. The `asOf` clock is supplied by the caller and is not authenticated.
- Five fixed probability bins [0, .2), [.2, .4), [.4, .6), [.6, .8), [.8, 1]. Reports mean predicted probability, observed up rate, Brier loss, count and descriptive Wilson 95% bin intervals when n >= 10; empty and undersized bins explicitly return null statistics. No smoothing, fabricated outcomes, or imputed missing bars.
- Overall Brier loss, binary log loss, 0.25 fixed 50% reference, Brier skill and expected calibration error (ECE) are reported. Negative skill means worse than the fixed baseline. No threshold here certifies statistical drift, predictive advantage or a tradable edge.

**Statistical limitations:** Wilson bin intervals assume independent Bernoulli observations; even non-overlapping horizons can remain serially dependent, and varying forecast probabilities within a bin are not identical Bernoulli parameters. Treat the intervals as *descriptive visual guides*, not valid coverage guarantees, multiple-comparison-adjusted significance tests or trading signals. ECE is sample-dependent and upward biased in finite samples. A 50% baseline may be weak for imbalanced regimes. None of these scores includes spread, executable ask/bid, commission, slippage, financing, leverage, margin, order rejection, liquidation, or drawdown. No real-market performance was measured.

Local checks: `cd frontend && node --experimental-strip-types --test tests/forward-reliability.test.ts` (8 synthetic regression tests); `npm test` and `npm run build` in CI. Test fixtures are invented and **not** market data. This module is intentionally disconnected and additive to PR #27's offline forecast review candidates.

## Loop 1 handoff

First establish an owner-authorized, source-identified completed-candle stream with trusted server-owned receipt timestamps, verified venue/timeframe/price side, documented market closures and entitlement. Then build append-only transactional issuance/settlement/outbox storage with crash recovery, authenticated notification delivery and durable deduplication; test delayed, reordered, stale and revised candles. Only evaluate real prospective calibration after independently verifiable ingestion, and keep live-order submission disabled pending broker eligibility, fresh executable quote, hard risk limits and explicit confirmation of each order.
