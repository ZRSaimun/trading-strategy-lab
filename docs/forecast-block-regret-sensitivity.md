# Loop 5: offline chronological five-block regret fragility (29 October 2026)

`app.forecast_block_regret_sensitivity.audit_block_regret_sensitivity`
performs a **read-only, disconnected** five-block omission stress test on a
preselected chronological, nonoverlapping, causally baseline-eligible,
**fully settled** forecast evaluation cohort.

The caller `audit_causal_climatology` first freezes evaluation membership
before reading labels, builds horizon/model-isolated strictly historical
Jeffreys-smoothed baseline forecasts, and applies its existing minimum scored
and unavailable-outcome gates. This diagnostic is **withheld** if those gates
fail or if **any** baseline-eligible outcome is unavailable, including pending,
void or post-cutoff settlement. It never fills in missing labels.

The fixed five blocks are contiguous in scored forecast index order, not
calendar-day partitions. Block sizes differ by at most one; any remainder is
assigned to the earliest blocks. Each block must contain at least 30 disjoint
scores, requiring **at least 150** scored observations per exact model/horizon.
For each of five predeclared omissions, the audit recomputes the **mean
paired Brier regret** and **mean paired log-loss regret** of the other four
blocks. Regret is issued forecast loss minus causal-baseline loss; positive
means relative underperformance. It returns the minimum/maximum retained
mean regret across the five omissions and the zero-based inclusive omitted
cohort ranges. It does **not** choose or remove a favorable block from any
real performance report. The original full-cohort scores are unchanged.

Fields per model/horizon:

- `blockRegretSensitivityStatus`:
  `BASELINE_SCORE_WITHHELD`, `MISSING_ELIGIBLE_OUTCOMES`,
  `INSUFFICIENT_CONTIGUOUS_BLOCK_SUPPORT`, or `DESCRIPTIVE_ONLY`.
- `blockRegretSensitivity`: null when the upstream causal/missingness
  gates fail; otherwise contains the block support, omitted ranges,
  `retainedMeanBrierRegretBestCase/WorstCase` and
  `retainedMeanLogLossRegretBestCase/WorstCase`. Numerical fields and
  ranges are null if fewer than 150 scored observations are available.
- All authentication, holdout, notification, paper and live execution
  authorization flags remain **false**.

This is a **descriptive in-sample fragility check**, not a bootstrap,
confidence interval, multiple-testing-corrected significance test, source
authentication, independent forward validation, proof of independence, or
trading P&L. A negative regret in all five omissions is not evidence of a
tradeable edge. Regime shifts, dependence between adjacent disjoint
forecasts, selection effects, and unauthenticated timestamps remain.

Synthetic tests (no market feed or broker):
`cd backend && PYTHONPATH=. pytest -q tests/test_forecast_block_regret_sensitivity.py tests/test_forecast_causal_climatology.py`

No new worker, schedule, alert, API route, payment, broker order, data
mutation, or credential use. Keep the large draft PR unmerged/undeployed
until full exact-head CI, independently verified backup restoration,
rollback rehearsal and authenticated production health.

**Loop 1 handoff:** independently authenticated, entitled prospective
completed-candle receipts; trusted server-owned UTC custody; provider,
price side, session and interval lineage; expected issuance and missing-bar
reconciliation. Historical BID candles are not live executable quotes.
