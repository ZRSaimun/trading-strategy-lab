# Hypothetical execution-friction stress (offline only)

The pure `frontend/lib/sweep-risk-path-friction-scenarios.ts` helper adds a **predeclared, reproducible sensitivity model** to the completed 1H sweep/MSS-proxy/FVG OHLC paths in draft PR #24. It consumes only an already source-isolated `RiskPathReport`, first calls the independent risk-path regime auditor to reject inconsistent trades, and never fetches prices or sends orders.

For each of 1–10 named frozen scenarios, it deducts five separately stated **nonnegative illustrative** components from gross directional bps: round-trip spread, adverse entry slippage, adverse exit slippage, round-trip commission, and a pro-rata `financingBpsPer24Hours × elapsed UTC days`. The five components **replace** the original report's 0/5/15 bps flat cost; they are not added to it. The calculation returns average net bps, average net R (using ex-ante stop distance), mean/min/max assumed costs, and fraction of positive completed paths. It rejects malformed scenario IDs, duplicate names, nonfinite or negative components, components over 1000 bps, inconsistent source report arithmetic, and elapsed holds longer than the predeclared 1H maximum.

**Important limitations:** This is *not* a real CFD fill or fee model. HistData BID-only OHLC does not establish executable bid/ask, broker-specific spreads, commission minimums, market impact, margin, FX settlement, actual daily financing/swap cutoff, weekend triple swap, or quote authentication. Elapsed-UTC pro-rata financing is a deliberate illustrative sensitivity, not a claim about a broker's charging convention. No real, demo or paper order is placed; no claim of profitable predictions. This helper is disconnected from the website and is not an execution eligibility gate.

## Reproduce

From `frontend`:

```sh
node --experimental-strip-types --test tests/sweep-risk-path-friction-scenarios.test.ts
npm run typecheck
npm test
```

The nine synthetic tests check decomposition, cost replacement rather than double-counting, elapsed time, high-cost losses, deterministic outputs, empty paths, malformed scenarios, impossible durations, arithmetic tampering and source identity. They test code, **not** actual market performance.

## Handoff and release gate

Before any prospective paper study, independently authenticate completed bid/ask quote provenance, real contract point value and financing schedule, pre-register cost assumptions and chronological holdout boundaries, and reconcile owner-authorized demo statements in PR #25. PR #29's holdout audit remains separate; no new historical archive is an untouched holdout. This module must remain draft/unmerged/undeployed until current-head frontend/backend/Docker/cloud CI and exact Render production workspace, backup, rollback and health checks are verified. Do not enable unsupported Trading 212 CFD endpoints or real-money order authority.
