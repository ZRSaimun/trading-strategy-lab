# Confluence risk-path cost and UTC-year regime stress (offline research)

This pure TypeScript helper lives in `frontend/lib/sweep-risk-path-regime-stress.ts`. It consumes **one source-isolated** `sweep-confluence-ohlc-risk-path-v1` report from PR #24. It does not fetch prices, fit thresholds, choose trades, connect to a broker, submit paper/real orders or change the production database.

For each **already frozen** round-trip cost scenario, the audit reports net mean basis points, mean net R, fraction of hypothetical net-positive paths, longest negative-net-R run, best/worst net R and peak-to-trough **additive** cumulative-R drawdown. It partitions the same observations by UTC calendar year of entry and reports independent entry-week counts. Annual partitions are descriptive, **not untouched holdouts**; do not optimize by choosing the best year.

The two signed hypothetical break-even cost thresholds are:

- `meanBpsBreakevenCost = mean(grossBps)`
- `meanRBreakevenCost = mean(grossBps / riskBps) / mean(1 / riskBps)`

Here `riskBps` is the pre-entry stop distance / entry price × 10,000. A **negative** threshold means no nonnegative trading cost makes that mean positive. A positive threshold is **not** an observed broker spread or a safe execution budget. With no completed paths, both thresholds and drawdown are null. The R drawdown is an additive trade statistic, **not** compounded account equity, margin drawdown, or position sizing.

The helper rejects inconsistent source/engine identity, chronology/overlap, stop and target geometry, gross/net return arithmetic, scenario costs, counters and reported means. It does not validate licensed quote authenticity, actual spread, financing, slippage, broker fills or exchange calendars. Existing retrospective HistData BID/OHLC studies were already inspected and cannot be relabelled out-of-sample. No profitable edge or real trading readiness is established.

From `frontend`, run `node --experimental-strip-types --test tests/sweep-risk-path-regime-stress.test.ts`, `npm run typecheck`, and full backend/frontend/Docker/free-cloud CI. This is an isolated library and synthetic test, **not wired to the website**. Do not merge/deploy PR #24 until current-head CI and exact Render production workspace, backup, rollback and health checks are verified. Next handoff: pre-register cost scenarios and test genuinely untouched source-verified chronological periods, then reconcile prospective demo fills with authenticated executable bid/ask, swap and contract terms.