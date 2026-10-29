# Loop 5: causal climatology comparator (disconnected research)

The offline-only function audit_causal_climatology compares frozen issued
probabilities with a causal Jeffreys-smoothed empirical UP-rate baseline.
It accepts only a replay-validated ForecastEventStore.load snapshot and a
caller-declared evaluation cutoff. It performs no I/O.

For each exact model and horizon (1, 3, 12), a fixed nonoverlapping
training census is selected by base and target candle BEFORE outcome status
is inspected. A training label counts only if its declared settled receipt
strictly predates the forecast issuance. Unknown, pending, void, late and
overlapping labels never become invented outcomes. The baseline probability
is (prior_up + 0.5)/(prior_count + 1), the Jeffreys Beta(1/2,1/2)
posterior mean. Baseline and issued probabilities are scored on the SAME
settled rows using paired Brier and Bernoulli log-loss regret.

The evaluation census is now also fixed **before** inspecting any outcome:
for each model/horizon in issuance order, a matured forecast is admitted
only when its base candle starts strictly after the last admitted target
candle. This conservatively prevents shared base/target closes and
horizon-overlapping forecasts from inflating the minimum 30 scored
observations. Missing/void labels and training-insufficient members still
occupy their predetermined census slots. `maturedAtDeclaredCutoff`
counts all matured issued forecasts, `nonoverlappingMaturedCensus` counts
preselected disjoint members, and `overlappingMaturedExcluded` counts
excluded overlaps. The two latter counts sum to the matured count.

### Fixed eligible-census missing-label regret sensitivity (29 October 2026)

The paired Brier and log-loss regrets on scored observations are supplemented
by **sharp best/worst binary-label counterfactual bounds** on the fixed,
nonoverlapping **baseline-eligible** evaluation census:

- `pairedBrierRegretBestCaseEligibleCensus` and
  `pairedBrierRegretWorstCaseEligibleCensus`;
- `pairedLogLossRegretBestCaseEligibleCensus` and
  `pairedLogLossRegretWorstCaseEligibleCensus`.

For each eligible forecast, the comparator freezes its causal Jeffreys
baseline from labels received **strictly before issuance**, even when the
forecast's own outcome is pending, void or declared settled only after the
evaluation cutoff. On scored rows it uses the observed paired loss difference
(issued minus baseline). On unavailable rows it considers both hypothetical
UP and DOWN outcomes, and sums the smaller/larger *paired* differences. The
denominator is **all baseline-eligible forecasts**, not the scored-only count.
This preserves shared-label pairing; subtracting independently optimized
issued and baseline losses would give incorrect regret bounds. No unknown
outcome is filled into the journal or counted as a realized settlement.

All four bounds remain null when the existing disjoint scored-sample or
missingness gate withholds metrics. With no unavailable eligible outcomes,
both bounds equal the observed paired regret. A positive lower bound is still
not evidence of statistically significant forecast skill or a tradeable edge:
the source, cutoff, costs and sample independence are unverified. VOID_GAP
may not have a definable binary target at all, so the bounds are explicitly
counterfactual sensitivity scenarios, not measured accuracy or returns.

Default minimum: 30 observed prior nonoverlapping outcomes and 30 scored
evaluations **on the disjoint evaluation census** per model/horizon. Training and evaluation missingness above
10 percent withhold performance. Evaluation cutoff cannot precede any
issuance, and labels after it remain unavailable.

LIMITATIONS: No authenticated vendor receipt, trusted clock, protected
holdout, executable bid/ask, transaction costs, independent fills, measured
returns or statistical significance. Disjoint sampling reduces mechanical overlap but not serial dependence,
selection and regime shifts remain. Positive scores cannot authorize trades.
Every notification/paper/live permission is false, and financial returns
and maximum drawdown are null. No production route, feed, worker, broker,
payment, dataset write or alert is enabled.

Tests: cd backend && PYTHONPATH=. pytest -q tests/test_forecast_causal_climatology.py

Loop 1 handoff: independently authenticated entitled prospective completed
candles, trusted server UTC custody, provider/side/session lineage and
missing-issuance reconciliation. Keep draft/undeployed until exact-head CI,
restorable backup, rollback rehearsal and authenticated production health.


### Fixed chronological disjoint half-split (29 October 2026)

When a model/horizon has at least **60** scored nonoverlapping forecasts,
passes the existing causal training and evaluation gates, and has **zero**
unavailable outcomes in its baseline-eligible census, the comparator reports
an early-versus-late split of the same chronological scored census. The
early half has floor(scored/2) observations, the late half has the rest;
each must contain at least 30. It exposes early and late paired Brier and
log-loss regrets (issued minus causal baseline), and LateMinusEarly
differences. Positive regret means issued forecasts score worse than the
historical causal comparator; a positive late-minus-early difference
indicates descriptive relative deterioration. These are NOT tests of
statistical significance, stationarity, independence or tradeable edge.

temporalSplitStatus explains abstention: BASELINE_SCORE_WITHHELD,
MISSING_ELIGIBLE_OUTCOMES, or INSUFFICIENT_TEMPORAL_SPLIT_SAMPLE.
All counts and split losses are null when withheld. Missing labels are
never silently dropped to construct favorable-looking regime halves.
The fixed disjoint census is unchanged, and no future label enters a
past causal baseline. This offline diagnostic neither authenticates
market data nor authorizes notifications, paper fills or broker orders.


### Chronological signed calibration drift (29 October 2026)

The same frozen, nonoverlapping chronological scored census used for paired
regret now reports early/late mean issued UP probability, early/late observed
UP fraction, and the **signed calibration gap** (mean issued UP probability
minus observed UP fraction). A positive gap means the model predicted UP more
often than UP occurred in that half; a negative gap means the opposite.
`temporalSplitSignedCalibrationGapLateMinusEarly` is the late signed gap
minus the early signed gap. It is a descriptive change, **not** a confidence
interval, drift hypothesis test, or calibrated trading signal.

These seven fields are withheld (null) unless the existing causal baseline
evaluation passes, the fixed eligible census has **zero missing outcomes**,
and each chronological half has at least **30 disjoint scored forecasts**.
The probability and outcome aggregates use exactly the same preselected
members, without selecting favorable statuses or retroactively changing
issued probabilities. The underlying journal and cutoff remain
unauthenticated, so apparent calibration changes are not independently
verified forward results. No notification, paper order or live execution
permission is granted.


### Fixed-bin reliability on disjoint forecast evaluations (29 October 2026)

The offline comparator also reports `fixedBinReliabilityStatus` and a
`fixedBinReliability` census. Exactly five **predeclared** probability bins
[0,.2), [.2,.4), [.4,.6), [.6,.8), [.8,1] prevent outcome-selected bin
boundaries. The input is the *same frozen, nonoverlapping, causally eligible
scored population* as the paired-regret and chronological calibration metrics.
The diagnostic is withheld entirely if the baseline score is withheld or any
eligible outcome is missing; unknown outcomes are never assigned labels.

Each occupied bin must contain at least 30 observations before its mean issued
UP probability, observed UP frequency and absolute gap are exposed. Sparse
bins reveal counts only. A weighted absolute calibration gap is reported only
if **at least two distinct probability bins** are occupied and **every
occupied bin** has at least 30 observations. Otherwise the status is
`INSUFFICIENT_BIN_SUPPORT` or `LIMITED_PROBABILITY_COVERAGE`, and the
weighted gap is null. Empty bins have null metrics. A single well-populated
bin cannot establish calibration across a range of forecast probabilities.

These are **descriptive**, not statistical confidence intervals or tests:
serial dependence, market regimes, arbitrary fixed bins, selection effects,
unverified sources and absence of independent holdout remain. A small
calibration gap is not an actionable signal, independent profitability
evidence, a broker quote or permission to notify or trade. No production
route, API credential, order, alert or dataset mutation is added.


### Single-outcome label-flip sensitivity (29 October 2026)

For an otherwise supported five-bin reliability population, the disconnected
audit now reports `singleOutcomeFlipBestCaseWeightedGap` and
`singleOutcomeFlipWorstCaseWeightedGap`. They enumerate every feasible
**exactly one** binary outcome flip in the frozen, nonoverlapping scored
population, recomputing the weighted absolute calibration gap with the same
issued probabilities, five bins, counts and denominator. A DOWN-to-UP flip
is feasible only where a DOWN outcome was observed, and vice versa. The
range is a hypothetical one-label data-quality stress, **not** a corrected
score, probabilistic confidence interval, hypothesis test or source
authentication. The original journal, labels and bin report are unchanged.

Both values are null when the weighted gap is withheld for sparse occupied
bins or fewer than two occupied bins. The comparator's upstream missing
eligible outcome and causal training gates continue to withhold the entire
fixed-bin report. No additional market feed, broker access, notification,
order or production write is enabled. Tests:
`cd backend && PYTHONPATH=. pytest -q tests/test_forecast_fixed_bin_sensitivity.py`.


### Leave-one-probability-bin-out calibration fragility (29 October 2026)

The disconnected five-bin audit additionally reports
`leaveOneBinOutStatus`, `leaveOneBinOutBestCaseWeightedGap`, and
`leaveOneBinOutWorstCaseWeightedGap`. For each occupied predeclared
probability bin, it removes **all** forecasts in that bin and recalculates
the remaining population-weighted absolute calibration gap. The range
describes how sensitive the aggregate is to one probability region;
the denominator is the count of **remaining** observations, not the
original cohort size. Original bins, issued probabilities and labels are
never changed.

Both numeric values are withheld unless the ordinary five-bin reliability
status is `DESCRIPTIVE_ONLY` **and at least three occupied bins** each
meet the 30-observation minimum. This leaves at least two supported
probability regions after any omission. A two-bin cohort reports
`INSUFFICIENT_REMAINING_BINS`; sparse or otherwise unsupported cohorts
report `RELIABILITY_WITHHELD`. The audit is an *in-sample descriptive
stress test*, not a model-selection procedure, confidence interval,
causal estimate or improvement to actual predictive performance.
Comparing omitted populations must not be used to cherry-pick a
favorable backtest. The existing upstream no-missing-outcomes gate,
source/provenance limitations and false notification/paper/live
permissions are unchanged.

Synthetic tests: `cd backend && PYTHONPATH=. pytest -q
tests/test_forecast_fixed_bin_leave_one_out.py`.


### Chronological paired-regret underperformance runs (29 October 2026)

The disconnected comparator now includes `chronologicalRegretRunStatus` and
`chronologicalRegretRuns` for each **exact model/horizon**, computed only
from its already-frozen, chronological, nonoverlapping and causally eligible
scored forecast cohort. It reports the **largest contiguous cumulative
positive net paired Brier and log-loss regret** (issued forecast loss minus
causal-baseline loss), together with the longest uninterrupted run of
strictly positive paired regret for each scoring rule. A negative regret
reduces the running adverse excursion; an all-favorable cohort reports zero.
These numbers are in **scoring-loss units**, not pounds, dollars, position
drawdown, trading returns, expected profit, or a probability of future loss.

The entire run report is null if the baseline scored-sample gate fails or
**any** eligible outcome is unavailable at the declared evaluation cutoff,
even when the primary paired score is descriptive. No selective deletion of
pending/void outcomes can manufacture a favorable-looking worst run.
The standalone helper validates finite bounded loss differences, has a
30-observation default gate and never authenticates source or holdout.
It does not select a model or optimize a threshold. Serial dependence,
regime changes, forecast selection, missing issuance and unauthenticated
clocks remain unaddressed; a large run is descriptive fragility, not a
significance test. All notification, paper-order and live-order permissions
remain false.

Synthetic tests:
`cd backend && PYTHONPATH=. pytest -q tests/test_forecast_regret_run_audit.py tests/test_forecast_causal_climatology.py`.
Keep draft and undeployed pending exact-head CI, source-rights/provenance,
independent prospective receipts, restorable backup, rollback rehearsal and
authenticated production health.
