# Frozen weekly sign-symmetry negative-control stress (offline only)

This research-only, non-executing helper consumes an existing completed **source-isolated** 1H confluence OHLC risk-path report. It first invokes the independent cost/regime auditor to reject inconsistent source identity, prices, trade chronology, overlapping simulated positions, counters, cost arithmetic and means. It requires the **pre-existing 5 bps illustrative** round-trip cost scenario and never fits parameters, changes signals, queries providers or places paper/live orders.

## Predeclared calculation

1. Assign each completed hypothetical entry to a Monday-start **UTC calendar week**. Average each week's 5 bps net R; give every nonempty week equal weight. The observed statistic is the mean of those weekly means, not the trade-weighted mean.
2. Generate a **symmetric sign-flip reference distribution** by multiplying each complete week's mean net R by either +1 or −1. For 12–16 weeks enumerate every one of the 2^N sign configurations; for more than 16 weeks use 8,192 deterministic pseudorandom sign configurations (fixed seed 20261024). Report the fraction with absolute magnitude at least as large as the observed statistic and the 2.5/97.5 percentiles of the reference distribution.
3. Report the maximum absolute weekly contribution divided by the sum of all absolute weekly contributions. This is a descriptive concentration measure, **not** an equity drawdown, variance estimate, or effect size.
4. **Withhold** all return/reference/concentration results when fewer than 30 completed paths or 12 distinct UTC weeks exist; keep explicit counts and the withholding reason. Reject more than 5,200 distinct weeks to bound computational work.

## Interpretation and limitations

The tail fraction is a **diagnostic null-reference frequency, not a p-value or valid significance claim**. Independent, sign-symmetric weekly returns under a zero-mean null are strong assumptions; market drift, clustered regimes, calendar seasonality, repeated testing, selected signals and previously inspected data can invalidate the interpretation. The helper makes no independence or symmetry verification and does not adjust for other tested hypotheses. Exact enumeration removes random Monte Carlo error for 12–16 weeks; seeded Monte Carlo has sampling error above 16 weeks.

A negative-control stress is useful for *falsification and caution*, not proving a trading edge. The 5 bps cost is illustrative and not a verified CFD spread, slippage, commission or financing charge. Historical BID/OHLC fills, source labels and freeze claims are not independently authenticated. This is not untouched chronological validation, executable broker quotes, demo fill reconciliation or authorization to trade. `eligibleForLiveTrading` is always false.

## Verification and release

Run `cd frontend && npm test && npm run typecheck && npm run build` and verify the **exact-head** backend, frontend, Docker and free-cloud CI. This feature adds three isolated files to draft research PR #24. Do not merge or deploy until main/PR reconciliation and owner-confirmed production backup, rollback, restoration and health gates are independently verified. No paid APIs, secrets, private archives or production data are involved.
