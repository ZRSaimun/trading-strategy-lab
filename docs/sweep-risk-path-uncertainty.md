# Frozen confluence OHLC risk-path uncertainty (offline only)

`frontend/lib/sweep-risk-path-uncertainty.ts` independently audits a completed `sweep-confluence-ohlc-risk-path-v1` report and computes deterministic descriptive uncertainty. It does not fetch market data, place demo/paper/live orders, use broker endpoints, or modify production state.

## Validation and protocol

- Require exact study/engine identity, source dataset ID, instrument, frozen path parameters, sorted unique explicit cost scenarios, non-overlapping causal trade chronology and complete accounting of closed/excluded/pending signals.
- Recompute each trade's directional gross bps from entry/exit, verify directional stop and target, conservative stop/target fills, net bps after each cost scenario and net R using the ex-ante stop distance. Reject tampered counts, prices, costs, R or summary means.
- Group entry timestamps by **UTC Monday-starting weeks**. Bootstrap whole weeks with replacement, 3,000 draws and a reproducible predeclared seed; preserve within-week trade clustering. Return descriptive 2.5%/97.5% quantiles for mean net bps and mean net R under each cost.
- With fewer than **30 closed paths or 12 distinct UTC weeks**, return `INSUFFICIENT_EVIDENCE` and **null** interval bounds. Zero observations have null mean, never zero-profit inference.
- Report stop/target/time exit counts. Never calculate p-values or mark an edge statistically significant. This threshold is an audit display policy, not a power calculation or validation guarantee.

## Reproduce

From `frontend`:

```sh
node --experimental-strip-types --test tests/sweep-risk-path-uncertainty.test.ts
npm run typecheck
npm test
```

Nine synthetic tests cover reproducibility, missing evidence, zero observations, cost/R tampering, invalid aggregate counts, chronology, fabricated exits, invalid identities and parameter configurations. Synthetic test returns **are not real strategy performance**.

## Interpretation, limitations and release

This is **not an untouched holdout**: prior 26-archive results and their 41 Nasdaq hypothetical OHLC paths were already inspected. Even an interval excluding zero would not prove a profitable executable strategy. UTC-week resampling assumes independent weeks, does not correct multiple hypothesis testing or regime dependence, and cannot fix provider timestamps, bid/ask execution, spreads, slippage, financing, settlement currency, fees or survivorship bias. No licensed candle or source archive is committed.

The helper is intentionally not wired to production UI or order execution. **Keep the draft PR unmerged and undeployed** until current-head backend/frontend/Docker/cloud CI is green and the exact Render production workspace, backups, rollback and post-deploy health are verified. Main may auto-deploy.

**Handoff:** Freeze strategy parameters and a genuine new source-isolated, owner-authorized chronological holdout before evaluating it. Validate cost and quote provenance against authenticated eligible demo-broker fills, then run a prospective paper journal. Never infer Trading 212 CFD API support or permit autonomous real-money orders without explicit owner confirmation per order.
