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
The absolute global calibration gap can conceal offsetting errors: for example,
low-probability forecasts that always resolve UP and high-probability forecasts
that always resolve DOWN may have identical overall mean probability and
observed-up rate. Ten-bin ECE measures the weighted absolute within-bin gaps
on the **same frozen, nonoverlapping late scoring census**. It is withheld
whenever the other metrics are withheld. Bin boundaries are fixed in advance
(no data-dependent bin tuning); sparse bins, dependent observations and
finite-sample binning bias make this descriptive, not a calibrated guarantee
or significance test. See Guo et al., *On Calibration of Modern Neural
Networks* (2017), https://arxiv.org/abs/1706.04599, for calibration context.

A Brier increase of at least 0.05 is a configurable *review flag*, not a
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


## ECE bin-population diagnostics (27 October 2026)

When the existing chronology, sample-size and dual missingness gates pass,
`lateEceBins10` exposes the **same fixed late scoring census** used by
`lateExpectedCalibrationError10`: ten ordered bins with zero-based `bin`,
`count`, `meanProbability` and `observedUpRate`. Bin `i` covers
probabilities from `i/10` inclusive to `(i+1)/10` exclusive, except bin
9 also includes 1.0. Empty bins have count zero and **null** rates rather
than fabricated zeros. The counts sum to `lateNonoverlappingSettled`, and
the count-weighted absolute difference between the two non-null rates
reconstructs ECE. Both ECE and the bin diagnostics are **null** when any
performance gate fails. Inspect occupied-bin counts before interpreting ECE:
a cohort with 30 observations spread across ten bins cannot provide
reliable within-bin calibration estimates. These diagnostics do not
establish statistical significance, independent data provenance, or
live-trading readiness.


## Sparse-bin uncertainty diagnostics (27 October 2026)

Each occupied `lateEceBins10` bucket now includes
`observedUpWilson95Descriptive` (two bounded endpoints for a nominal 95%
Wilson binomial interval) and `lowSupportUnder30` (true when its settled
count is below 30). Empty bins have **null** intervals and support flags,
never invented certainty. `lateEceOccupiedBinsUnder30` and
`lateEceMinOccupiedBinCount` summarize occupied-bin support; all new
diagnostics are **null** when the existing sample-size or missingness gates
withhold ECE. A bin with 40 observations is not automatically statistically
adequate: market outcomes may be serially dependent and regimes may change.
These intervals assume independent Bernoulli trials and therefore **do not
have validated 95% coverage on market data**. They are review aids, not
calibration certification, alert authorization or a trading signal. No
independent market receipts, broker quotes or forward P&L were used.


## Bernoulli log-score diagnostic (27 October 2026)

The same fixed, nonoverlapping, chronologically eligible settled cohorts now
report `earlyLogLoss`, `lateLogLoss`, and `lateLogLossDelta` (late minus
early), measured as mean Bernoulli negative log-likelihood in **nats**. The
`lateLogLossSkillVsFrozenEarlyClimatology` is
`1 - lateLogLoss / frozenEarlyClimatologyLogLoss`, where the smoothed early
up-frequency is fitted exclusively from outcomes available before the late
cohort starts. Lower log loss is better; negative skill is worse than that
frozen baseline. Unlike Brier, log loss especially penalizes confident wrong
predictions. Probabilities must be finite and strictly between zero and one,
and `log1p` is used for numerical stability near zero.

All four log-score fields are **null** when any existing sample-size,
chronology, issued-stream or fixed-census missingness gate withholds scores.
The Brier-based descriptive drift flag and thresholds are unchanged; this
addition does not constitute a second trading signal or statistical test.
The samples remain retrospective, dependent and unauthenticated. **Log loss
is a probabilistic scoring rule, not monetary trading loss, returns, proof
of calibration, or broker-executable price evidence.** No live alerts, paper
fills, real orders or production writes are enabled.


## Optional declared as-of settlement cutoff (27 October 2026)

Call `audit_temporal_forecast_calibration(snapshot, evaluation_as_of=...)` with
a caller-declared **integer UTC epoch-second cutoff** to prohibit the late
evaluation cohort from learning labels whose `resolvedAt` is **after** that
cutoff. The cutoff must be at or after **every issued forecast** in the
supplied snapshot; invalid, negative, boolean, fractional and excessively
large cutoffs are rejected. A label resolved **exactly at** the cutoff
remains eligible. When omitted, the audit retains its previous explicitly
**retrospective** behaviour.

The fixed nonoverlapping issued census is selected **before** settlement
inspection. Settled labels resolved after the declared cutoff count as
unavailable in both the whole late issued stream and the selected census,
in addition to pending/void outcomes. Either unavailable fraction exceeding
the configured threshold withholds **all** calibration and drift scores.
New diagnostics are `lateSettledAfterDeclaredAsOf`,
`lateCensusSettledAfterDeclaredAsOf`,
`lateUnavailableAtDeclaredAsOfFraction` and
`lateCensusUnavailableAtDeclaredAsOfFraction`. Existing
`lateUnresolvedOrVoid` fields continue to count only pending/void outcomes.
The top-level `evaluationAsOfDeclared` echoes the cutoff and
`evaluationCutoffAuthenticated` is always **false**.

**Important:** The caller can choose or backdate this cutoff, and a later
journal snapshot does not prove the historical state of that journal at the
cutoff. This is a label-leakage *review fence*, not an independently
time-stamped prospective scorecard, a sealed holdout, authenticated
performance, an alert trigger or evidence of financial return. Independent
server receipt chronology, immutable snapshot anchors and provider-licensed
completed-candle data are required before stronger claims. No feed,
notification, paper fill, live order or deployment is activated.
