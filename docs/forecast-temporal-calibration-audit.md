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


## High-confidence forecast error census (27 October 2026)

When the existing chronology, minimum effective sample and both missingness
gates pass, the **fixed late nonoverlapping settled cohort** now reports the
realized binary classification error for predictions at or beyond 90% confidence:
probability >= 0.90 predicts UP and probability <= 0.10 predicts DOWN.
This is a fixed descriptive threshold, not a tuned strategy, trading signal,
alert trigger or a guarantee of 90% accuracy.

`lateHighConfidenceCount` counts the selected settled forecasts in those
tails, `lateHighConfidenceFractionOfSettled` shows their fraction of the
selected late cohort, and `lateHighConfidenceWrong` counts their incorrect
binary outcomes. `lateHighConfidenceWrongFraction` is the error rate
**conditional on a forecast being in a confidence tail**. It is **null**
when there are no qualifying forecasts. The nominal Wilson interval
`lateHighConfidenceWrongWilson95Descriptive` and the
`lateHighConfidenceLowSupportUnder30` flag are likewise null for empty
tails. When any existing performance gate fails, **all six fields are null**,
not false zeros.

A low tail error fraction does **not** establish probabilistic calibration:
even 90%-confidence forecasts can be wrong around 10% of the time in an
idealized independent population. Serial dependence, outcome selection,
unverified timestamps and retrospective evaluation mean Wilson coverage is
not validated. No prospective market data, executable BID/ASK quote,
real alert, broker call, paper fill, return or production change is involved.


## Binary-label missing-outcome Brier sensitivity (27 October 2026)

When **all existing** sample-size, chronology, whole-stream and selected-census
missingness gates pass, the report additionally exposes
`lateBrierBestCaseAllIssuedCensus` and
`lateBrierWorstCaseAllIssuedCensus`. The denominator is the **fixed
nonoverlapping late issued census**, not just settled forecasts. For each
eligible settled forecast, use its observed squared Brier error. For each
unavailable selected forecast (pending, void/gap or settled after a declared
as-of cutoff), compute the minimum and maximum of `p²` and `(1-p)²`.
The two sums divided by the fixed issued-census count bound the *hypothetical*
Brier score if every unavailable record could be assigned either binary label.

No missing outcome is imputed or written. A gap/void forecast may have **no
legitimate observable target**, so these are mathematical sensitivity
scenarios, **not** attainable realized returns, unbiased confidence intervals,
independent authentication or a claim that missing observations actually
resolved. If no selected labels are unavailable, both bounds equal
`lateBrier`; if an unavailable selected forecast has `p=.7`, its
counterfactual Brier contribution ranges from `0.09` to `0.49`.
Unselected missing records do not change the fixed-census bounds, but still
count against the whole-stream missingness gate. The bounds are **null**
whenever any performance gate withholds scores. No notification, demo fill,
live executable quote, order or production dataset is affected.


## Ten-bin Brier component audit (27 October 2026)

When all existing chronological, sample-size and issued/selected-census
missingness gates pass, the fixed late **nonoverlapping settled** forecast
sample now reports four *descriptive* fields:

- `lateBrierBinned10Reliability`: sum over occupied probability bins of
  bin weight times (mean forecast probability minus observed-up frequency)
  squared. Lower is better **conditional on this binning**.
- `lateBrierBinned10Resolution`: sum of bin weight times (observed-up
  frequency minus overall observed-up frequency) squared. Larger means
  bins separate different observed frequencies, not that the model is
  profitable.
- `lateBrierBinned10Uncertainty`: overall observed-up frequency times
  one minus that frequency. This is an outcome-prevalence property.
- `lateBrierBinned10Residual`: actual late Brier minus
  (reliability - resolution + uncertainty).

The **explicit signed residual is essential**: using ten probability
bins means individual probabilities can vary within each bin, so
reliability - resolution + uncertainty is generally **not** exactly
equal to the raw forecast Brier score. The four terms together
reconstruct `lateBrier` (up to floating-point rounding). A negative
residual is possible and is **not** a negative financial loss.
The binning is frozen at ten equal-width bins and shares the existing
`lateEceBins10` population. This is a *binned Murphy-style
diagnostic*, not an exact per-probability decomposition, statistical
significance test, holdout result, trading edge or new alert trigger.

All four fields are `null` when the existing evaluation gates withhold
Brier, including a declared as-of cutoff that excludes too many
late-settling labels. Sparse bins, serial dependence, repeated peeking,
unauthenticated source receipts and unverified outcome clocks remain.
The report grants no notification, paper fill or live order permission.


## Missing-outcome Bernoulli log-loss sensitivity (27 October 2026)

When **all existing** chronological, sample-size and dual issued-stream/fixed-census
missingness gates pass, `lateLogLossBestCaseAllIssuedCensus` and
`lateLogLossWorstCaseAllIssuedCensus` report counterfactual minimum and
maximum binary-label log loss (natural-log units, **not money**) on the
preselected **nonoverlapping late issued-forecast census**.

Eligible settled outcomes contribute their actual Bernoulli log score.
Each unavailable selected record (pending, void/gap, or settled after a
caller-declared as-of cutoff) contributes the smaller or larger of
`-ln(p)` and `-ln(1-p)`. Strictly interior finite probabilities are
already enforced by the existing journal validator; `log1p(-p)`
maintains precision near zero. The denominator includes **all selected
issued forecasts**, never just the settled subset. When all selected
labels are eligible, both bounds equal `lateLogLoss`. Unselected missing
records still count toward the whole-stream gate.

No missing outcomes are filled, stored, predicted or declared observed.
A void/gapped target may never have a legitimate binary outcome. These
are mathematical **sensitivity scenarios**, not confidence intervals,
realized log loss, independently authenticated calibration, financial
losses, profits, a trade signal or authorization for any alert or order.
Both fields remain `null` when any existing evaluation gate withholds
scores. The caller journal and cutoff are unauthenticated; genuine
forward verification requires Loop 1's entitled completed-candle
receipts, independently retained timestamp anchors and expected-bar
inventories. No notification, paper fill, broker call or deployment
is enabled by this change.


## Late log-loss tail concentration and paired regret (27 October 2026)

Four **descriptive, retrospective** diagnostics use exactly the same fixed
nonoverlapping, chronologically eligible settled late census as `lateLogLoss`.
They remain null under the existing minimum-sample, chronology and dual
missingness gates:

- `lateLogLossWorstSingle`: largest individual Bernoulli log loss.
- `lateLogLossP95NearestRank`: loss at sorted 1-based rank
  `ceil(0.95 * n)`; an empirical order statistic, **not** an interval.
- `lateLogLossTopDecileShare`: share of total late log loss contributed by
  the worst `ceil(n/10)` forecasts. This is **not** financial downside.
- `lateWorstSingleLogLossRegretVsFrozenEarlyClimatology`: maximum signed
  paired `model_loss - frozen_baseline_loss` on the same observed label.
  Negative means every eligible model loss was smaller than the baseline.

No missing labels are imputed, no sample or probabilities are reselected,
and no alert or execution authority is granted. Tail statistics are not
statistical significance, forward accuracy, realized trading returns or
drawdown. The caller journal, provider, timestamps and declared cutoff
remain unauthenticated; Loop 1 must provide independently anchored entitled
completed-candle evidence before prospective operational use.


## Eligible-outcome settlement-lag census (27 October 2026)

When the existing minimum-effective-sample, chronology, and **both**
missingness gates pass, three descriptive late-cohort fields report how
long the caller-declared journal took to settle each eligible forecast
**after its target candle closed**:

- `lateSettlementLagP95Seconds`: empirical nearest-rank 95th percentile
  of `resolvedAt - (targetStart + seconds)`.
- `lateSettlementLagMaxSeconds`: largest such delay in seconds.
- `lateSettlementLagOverOneCandleFraction`: fraction of eligible late
  outcomes whose settlement lag **strictly exceeds** one source candle.

Only the fixed, nonoverlapping, eligible **settled** late scoring census is
used. Outcomes resolved after `evaluation_as_of` are excluded and counted
as unavailable by the existing as-of missingness gate. Pending, void/gapped,
and excluded observations are **not** treated as zero-lag outcomes.
All three values remain **null** whenever existing scoring gates withhold
metrics. The nearest-rank P95 is a sample order statistic, not a latency
service-level guarantee, confidence interval, or market-data freshness proof.

These numbers measure **declared journal timestamps**, not independently
authenticated provider latency, server receipt times, exchange completion,
Telegram delivery, or broker execution. Selective missingness and the
unauthenticated caller-declared as-of cutoff remain material limitations.
No notifications, orders, paper fills, dataset writes or trading permissions
are enabled. Loop 1 still needs authenticated provider/source/price-side
completed-candle receipts, server-owned immutable timestamps, session-aware
expected-bar inventories and usage rights before operational activation.


## Full late-issued forecast timing census (27 October 2026)

Four additional **descriptive** fields quantify the caller-declared delay
between each completed base candle close and the corresponding forecast
issuance. Unlike outcome-scoring diagnostics, they cover **every forecast
issued in the late half of the model/horizon group**, including pending,
void, overlapping and as-of-unresolved forecasts. This avoids the
settled-outcome selection bias of reporting timing only for scored forecasts.

- `lateIssuanceLagCensusCount`: number of late issued forecasts included.
- `lateIssuanceLagP95Seconds`: empirical nearest-rank 95th-percentile
  `issuedAt - (baseStart + seconds)` over that entire late issuance cohort.
- `lateIssuanceLagMaxSeconds`: maximum of those declared issuance delays.
- `lateIssuanceLagOverHalfCandleFraction`: proportion with issuance delay
  **strictly greater** than half the candle duration.

The pre-existing causal chronology check requires issuance at or after base
close and before the next candle close. These fields remain available even
when calibration scores are withheld for missing outcomes or insufficient
nonoverlapping samples, because they do **not** inspect labels. They are
not a permission to notify or trade, nor an alert-delivery SLA.

**Limits:** the journal and `issuedAt` are caller-declared and not
independently timestamped; no authenticated market-data receipt or
notification acknowledgement is established. This census only covers
forecasts that were actually issued. Missing expected candles and
omitted forecasts require a separately authenticated session-aware
inventory (Loop 1 and Loop 5 PR #86). No real notifications, fills,
broker calls or production changes are enabled.


## All-issued forecast confidence population (27 October 2026)

Three **descriptive** fields report the probability distribution of **every
late issued forecast**, independently of whether its outcome settled:

- `lateIssuedHighConfidenceCount`: number of late issued forecasts with
  `p <= 0.10` or `p >= 0.90`, including both exact boundaries.
- `lateIssuedHighConfidenceFraction`: that count divided by **all late
  issued forecasts**, not the smaller nonoverlapping settled sample.
- `lateIssuedMeanProbability`: average issued UP probability across the
  same complete late issuance cohort.

Pending, void, overlapping and as-of-unresolved records remain in this
census. Thus high-confidence issuance cannot disappear merely because
selected outcomes are unavailable; the three fields remain descriptive
when the existing calibration/selection-risk gates withhold settled-outcome
scores. Compare them with the separately gated settled-only high-confidence
error audit to spot potential outcome-selection concerns. The threshold
is predeclared and is not tuned to returns.

**Limits:** the issuance journal and source are unauthenticated; missing
forecasts and expected candles are outside this population. A confidence
fraction is not forecast calibration, directional accuracy, statistical
significance, an alert trigger, executable BID/ASK evidence, paper P&L or
permission to place any order. Loop 1 still needs independently attested
completed-candle inventories and immutable issuance timestamps.


## High-confidence issuance versus declared delay (27 October 2026)

An outcome-independent cross-tab connects the **full late-issued confidence
population** with the **full late-issued timing population**, rather than
selecting forecasts with convenient settled labels. For the fixed thresholds
`p <= 0.10` or `p >= 0.90`, and strictly more than half the base-candle
duration after declared base close, it reports:

- `lateIssuedHighConfidenceDelayedOverHalfCandleCount`: delayed high-confidence
  forecasts in the entire late-issued cohort.
- `lateIssuedHighConfidenceDelayedOverHalfCandleFraction`: delayed count
  divided by **all high-confidence late-issued** forecasts, or null if none.
- `lateIssuedOtherDelayedOverHalfCandleFraction`: delayed fraction of the
  complementary `0.10 < p < 0.90` issuance population, or null if empty.

A forecast issued **exactly** half a candle after close is not in the delayed
count. Pending, void, overlapping and as-of-unresolved forecasts are included
without inspecting labels. These diagnostics remain available when Brier and
log-loss scores are withheld by the existing sample/chronology/missingness
gates. They do not change the gates, forecast issuance, alert delivery or
trading permissions.

**Interpretation:** A high-confidence forecast issued relatively late may
deserve human review for stale-signal risk, but this does not establish actual
feed delay, alert delivery, probability calibration, an executable opportunity,
or financial harm. Timestamps are caller-declared and source receipts are not
independently authenticated. Unissued forecasts and missing expected candles
are outside this census; PR #86 and Loop 1 require separately verified
completed-candle/session inventories. No live orders, demo fills, Telegram
messages or production changes are authorized by these statistics.


## Fixed-census probability-bin outcome availability (27 October 2026)

The new `lateCensusOutcomeAvailabilityBins10` diagnostic exposes possible
**probability-dependent outcome missingness** before attempting to interpret
calibration or drift. It uses the existing fixed, nonoverlapping **late issued**
census, selected without looking at outcome status. The same eligible settled
IDs used by the declared as-of scoring review determine availability, but
the outcome direction is never inspected. Each fixed-width probability bin
0 through 9 reports `issued`, `eligibleSettled`, `unavailable`,
`unavailableFraction`, and `lowSupportUnder30`. Empty bins have null rates
and null support flags. A settled result received after the declared as-of
cutoff is unavailable, not retroactively counted as known.

These counts remain visible when the minimum-sample or missingness gates
withhold Brier/log-loss metrics. They are **not** a missing-at-random test,
a calibrated forecast, a proof of source completeness, or a live trading
signal. Low-support bins are descriptive only; the journal cannot detect
forecasts never issued or absent completed candles. Independent Loop 1
provider/venue/side, receipt chronology, entitlement and session inventories
are still required. No alert, paper order, real order or production activation.


## Label-free issued probability distribution shift (27 October 2026)

The chronological review now compares the **full early and late issuance
populations** for each model/horizon, independently of whether a forecast's
outcome settled, was voided, or remains pending. It uses ten **fixed**
probability bins, with exact boundaries at 0.10, 0.20, etc. assigned to the
higher bin and bin 9 containing probabilities at or above 0.90.

- `earlyIssuedProbabilityBins10` and `lateIssuedProbabilityBins10`: integer
  counts across all issued forecasts, including overlapping observations.
- `issuedProbabilityJensenShannonBits10`: Jensen-Shannon divergence between
  the two normalized histograms, using base-2 logarithms; 0 means identical
  binned distributions and 1 means completely disjoint bin support.
  Null if either issuance cohort is empty.
- `issuedProbabilityShiftLowSupportUnder30`: true if either cohort has fewer
  than 30 issued forecasts, null when a cohort is empty.

This can expose **forecast-output distribution drift** even when unavailable
outcomes suppress retrospective Brier and log-loss metrics. It is not an
outcome-dependent sample, and the metric does not establish prediction
accuracy, causal drift, statistical significance, independent observations,
a trustworthy market source, or a profitable trading edge. Fixed bins can
hide within-bin shifts. No drift-based alert, paper fill or live order is
authorized. Independently authenticated completed-candle receipts and
market-session inventories remain Loop 1 prerequisites.


## Unbinned issued-probability ECDF shift (27 October 2026)

The all-issued early/late cohorts now also produce two **unbinned**
empirical cumulative-distribution-function (ECDF) distances:

- `issuedProbabilityWasserstein1`: exact one-dimensional Wasserstein-1
  distance, computed as the integral of the absolute ECDF difference across
  probability values. It is in **probability units**, between 0 and 1, and
  captures within-bin movement missed by the ten-bin Jensen-Shannon measure.
- `issuedProbabilityKsGap`: maximum absolute difference between the two
  empirical CDFs, between 0 and 1. This is a **descriptive KS distance**,
  **not** a Kolmogorov-Smirnov significance test or p-value.

Both are null if either cohort has zero issued forecasts. The existing
`issuedProbabilityShiftLowSupportUnder30` applies to both metrics, too.
Implementation sorts the exact issued probabilities and walks their merged
support, including ties and unequal cohort sizes; it never generates or
imputes observations. For example, cohorts fixed at 0.71 and 0.79 occupy
the same ten-bin histogram (zero binned Jensen-Shannon divergence), yet
have Wasserstein-1 distance 0.08 and descriptive KS gap 1.0. A large KS
gap with little W1 movement can reflect a small probability displacement,
not an economically significant change.

These metrics include **all** early/late issued forecasts before selecting
on settlement, as-of cutoff, or overlap. They cannot see **unissued**
forecasts or missing source candles. No p-values, independence assumptions,
market-source authentication, forecast skill, actual alerts, executable
BID/ASK, net paper P&L, or trading permissions follow from these distances.
Loop 1 must provide separately authenticated completed-candle/session
inventories and receipt timestamps before operational use.

## Signed issued-probability location, spread and confidence drift (27 October 2026)

The same **all-issued** early/late cohorts now also report:

- `earlyIssuedMeanProbability`: mean UP probability in the early cohort.
- `issuedProbabilityMeanShift`: late minus early mean UP probability (signed).
- `issuedProbabilityMedianShift`: late minus early midpoint median.
- `issuedProbabilityInterdecileRangeShift`: late minus early (nearest-rank p90 - p10), indicating wider/narrower output distributions.
- `earlyIssuedHighConfidenceFraction`: early share with p<=0.10 or p>=0.90.
- `issuedHighConfidenceFractionShift`: late minus early share above those confidence thresholds.

All six are null when either cohort is empty; they use no outcomes and are unchanged by pending, void, overlapping or as-of-unresolved settlement states. Signed shifts complement nonnegative W1/KS/JS distances: a zero mean shift can coexist with a much wider probability distribution. The existing `issuedProbabilityShiftLowSupportUnder30` flag applies. Nearest-rank quantiles are sample-sensitive, and confidence thresholds are fixed rather than optimized. These are not seasonality-adjusted, independent or statistically significant drift tests; journal source and issuance timestamps are not authenticated. No alert, paper order, live order or performance claim is authorized.


## UTC-hour issuance-mix and within-common-hour drift (27 October 2026)

The **all-issued** early/late cohorts now also report
`earlyIssuedUtcHourCounts24`, `lateIssuedUtcHourCounts24`,
`issuedUtcHourTotalVariation` (0 to 1), and
`issuedUtcHourCommonSupportFraction` (0 to 1). Hour is computed from
`(baseStart // 3600) % 24`, always **UTC**, not a guessed exchange-local
session or daylight-saving conversion. Counts include pending, void,
overlapping and unresolved forecasts; they do not select outcomes.

For hours present in both cohorts, `issuedUtcHourWithinCommonMeanShift`
computes the signed late-minus-early average UP-probability change within
each hour and averages those differences using the **predeclared overlap
weight** `min(early_hour_share, late_hour_share)`, normalized by their sum.
This avoids mistaking a pure change in the mix of UTC hours for a within-hour
change: a shift from mostly low-probability hour A to mostly high-probability
hour B can move the aggregate mean while leaving this diagnostic at zero.
`issuedUtcHourCommonHourCount` counts shared bins.
`issuedUtcHourCommonLowSupportUnder30` is true if any shared UTC hour has
fewer than 30 forecasts in either cohort. With **no common hours**, the
within-hour shift and support flag are null; with either cohort empty,
comparison metrics are null and the count arrays remain visible.

**Interpretation:** These are descriptive, label-free diagnostics, not
statistical significance tests, regime normalization, causal attribution,
or verified trading-session adjustments. A small shared-hour fraction
means the within-common-hour result covers little of the issued population.
UTC-hour matching does not control for weekdays, holidays, market closures,
seasonal regime changes, feed gaps, DST at venues, or dependence among
forecasts. Neither output authenticates source candles or establishes
calibration, executable BID/ASK, alert delivery, forward P&L, or trading
permission. Loop 1 still needs independent entitled source receipts,
server-owned timestamps and session-aware expected-bar inventories.


## Fixed-census UTC-hour outcome availability (28 October 2026)

Two additional 24-element arrays, `earlyCensusOutcomeAvailabilityUtcHour24`
and `lateCensusOutcomeAvailabilityUtcHour24`, expose **selection risk by UTC
base-candle hour**, including empty hours. Each element reports `utcHour`
(0–23), `issued`, `eligibleSettled`, `unavailable`,
`unavailableFraction`, and `lowSupportUnder30` (null for empty hours).
The denominators are the **preselected nonoverlapping issued-forecast
censuses**, not only successfully settled forecasts. An unavailable selected
forecast cannot be replaced by a conveniently settled overlapping neighbour.

Early eligibility excludes outcomes not known strictly before the late
cohort's first issuance; late eligibility excludes pending/void labels and
settlements later than the optional caller-declared `evaluation_as_of`.
The arrays remain visible when the existing score gate withholds Brier/log
loss. They can expose time-of-day-concentrated missing labels that a global
missingness percentage or probability-bin census conceals. They do not change
the existing gates, infer missing labels, or prove that missingness is random.

These are **UTC hour buckets**, not a validated exchange session calendar,
DST adjustment, independently verified data receipt, or significance test.
Sparse hours are flagged, and no hourly performance, live feed, notification,
paper fill, broker action, or trading authorization is inferred. Loop 1 must
independently attest completed-candle receipt times, provider/venue/side
provenance and expected market-session inventories before prospective use.

## UTC weekday outcome-availability census (28 October 2026)

The disconnected calibration audit now exposes
`earlyCensusOutcomeAvailabilityUtcWeekday7` and
`lateCensusOutcomeAvailabilityUtcWeekday7`. Each has seven ordered UTC
weekday buckets (`utcWeekdayMonday0`: Monday 0 through Sunday 6) with
`issued`, `eligibleSettled`, `unavailable`,
`unavailableFraction` and `lowSupportUnder30`. Empty weekdays retain
null rates. The buckets use the **same preselected nonoverlapping issued
census** as the existing calibration audit; a pending, void, boundary-purged
or as-of-excluded label stays unavailable and is never replaced by a
convenient neighbouring settled forecast. These counts remain visible even
when the scoring gates withhold Brier/log loss.

This complements UTC-hour missingness: a concentration of unavailable
outcomes on particular weekdays could be hidden in pooled hours. The
weekday comes solely from the caller-declared UTC base timestamp (Unix
epoch Thursday), **not** an independently authenticated exchange calendar.
It cannot distinguish closures, holidays, DST-related sessions, outages,
or deliberately omitted candle/forecast opportunities. PR #86 and Loop 1
still require an independent expected-bar register and authenticated
completed-candle receipts. All source, delivery, paper and live-trading
permissions remain false. No actual market, notification or order was used.
