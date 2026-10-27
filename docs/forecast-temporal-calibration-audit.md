# Loop 5 — chronological forecast calibration drift review (offline)

`backend/app/forecast_temporal_calibration_audit.py` adds an opt-in, read-only
**descriptive** chronological drift check for a `ForecastEventStore.load()`
snapshot. No API route, feed, worker, Telegram sender, order path, migration,
secret, broker request, or database write is enabled.

The audit first runs the existing scorecard's strict journal shape, event/outcome
linkage and source-isolation checks. For each separate model version and candle
horizon (1, 3, 12), it splits **all issued forecasts** by issuance order, never
by observed outcome. The first cohort's settled labels must have been resolved
**before** the second cohort begins; later-resolving training labels are purged.
Both cohorts first fix a nonoverlapping **issued-forecast census before
looking at outcome status** (including shared endpoint closes). Only then are
settled and chronologically available outcomes scored. This prevents a missing
or void outcome from shifting the sampling window onto a conveniently settled
neighbour. The report exposes both issued-census and eligible-settled counts.
Effective samples can be far smaller than issued forecasts.

When each cohort has at least 30 nonoverlapping settled outcomes and no more
than 10% unavailable records, report Brier scores, late-minus-early Brier,
late observed-up fraction, mean probability, absolute calibration gap,
**fixed ten-bin expected calibration error (ECE)**, and
late Brier skill versus a **frozen early-only Jeffreys-smoothed climatology**.
For the early cohort, unavailable means **pending + void + settled labels
resolved at or after the late cohort's first issuance**. These purged labels
cannot be used to fit the frozen baseline and must count toward the same
missingness threshold; otherwise delayed outcomes could silently bias the
reported early score. The audit reports `earlyPurgedForChronology`,
`earlyUnavailableAtBoundary`, and its fraction separately from the late
pending/void fraction. **Both** the whole issued-stream missingness rate and
the fixed nonoverlapping **scoring-census** missingness rate must be at or
below the threshold. Otherwise 3 missing selected labels out of 40 could be
diluted to 3/80 when 80 overlapping forecasts were issued. The report exposes
`earlyCensusUnavailableAtBoundary`, `lateCensusUnresolvedOrVoid` and their
corresponding `Fraction` fields. Census selection is frozen before outcome
inspection. This remains a descriptive selection-risk safeguard,
not independent authentication of outcome timing.
The absolute global calibration gap can conceal offsetting errors: for example,\nlow-probability forecasts that always resolve UP and high-probability forecasts\nthat always resolve DOWN may have identical overall mean probability and\nobserved-up rate. Ten-bin ECE measures the weighted absolute within-bin gaps\non the **same frozen, nonoverlapping late scoring census**. It is withheld\nwhenever the other metrics are withheld. Bin boundaries are fixed in advance\n(no data-dependent bin tuning); sparse bins, dependent observations and\nfinite-sample binning bias make this descriptive, not a calibrated guarantee\nor significance test. See Guo et al., *On Calibration of Modern Neural\nNetworks* (2017), https://arxiv.org/abs/1706.04599, for calibration context.\n\nA Brier increase of at least 0.05 is a configurable *review flag*, not a
significance test or proof of concept drift. Incomplete, sparse or selectively
resolved cohorts withhold all numerical performance scores. Early/late group
sizes and missingness remain visible.

Run locally: `cd backend && PYTHONPATH=. pytest -q tests/test_forecast_temporal_calibration_audit.py`.

**Limitations:** Caller journal is unauthenticated, and the chronological split
is not a locked, independently protected holdout. Serial dependence, overlapping
market regimes, repeated evaluation, selection bias, future source revisions and
multiple testing remain. There is no claim of statistical significance,
calibrated production forecasts, executable bid/ask, real delivery, forward
paper returns, costs, fills, drawdown or positive expectancy. Every notification,
paper-order and real-order permission remains **false**.

**Loop 1 handoff:** provide independently authenticated, entitled, server-timed
completed-candle receipts and a session-aware expected-bar inventory. Confirm
provenance, licensing and missingness independently before treating journal
outcomes as prospective. Keep this disconnected until exact-head CI, staging,
restorable backup, rollback and production health are independently verified.
