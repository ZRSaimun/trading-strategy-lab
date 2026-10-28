# Loop 5 — conservative forecast journal scorecard (disconnected)

`backend/app/forecast_prospective_scorecard.py` is an opt-in **read-only** summary of an already validated `ForecastEventStore.load(session_id)` result. It adds no route, scheduler, feed, broker, alert sender, table or migration. It does not modify database records. The journal source is explicitly **unauthenticated**, even if the input calls itself prospective.

Group by immutable model version and candle horizon (1, 3, 12), never mix providers or instruments (the underlying journal is source-isolated). Count **all issued forecasts** in the denominator: settled, pending and void-on-gap. With fewer than 30 settled outcomes in a group, withhold performance scores. At or above the minimum, report conditional-on-settlement Brier, log loss, equal-width-bin ECE, up frequency, directional accuracy for non-0.5 predictions and a descriptive Wilson interval. These are *forecast quality descriptors*, not validated statistical inference or trading profitability. A 0.5 prediction abstains from directional accuracy, but still contributes to Brier/calibration/log loss.

The function checks identity, event/outcome linkage, status and timing consistency and fails closed on malformed or conflicting records. It **does not independently authenticate** provider receipts or establish that data arrived live; callers must use `ForecastEventStore.load`, not arbitrary dictionaries. The journal's internal digest is not independently tamper-proof.

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_forecast_prospective_scorecard.py`.

**Interpretation caveats:** Overlapping 1/3/12-candle targets are dependent; void and pending outcomes can create selection bias; calibration binning and the Wilson interval are descriptive only. Scores may reflect a fabricated or unrepresentative data source. There are no genuine bid/ask execution quotes, spread/slippage/commission/financing adjustments, broker fill reconciliation, net returns or drawdown. No real-money order may be placed on these scores. Production remains unchanged.

## Loop 1 handoff

Provide entitled authenticated completed-candle observations with exact provider/venue/instrument/side, trusted server receipt times, session-aware closure/gap policy and independently verifiable source receipts. Validate durable journal replay, PostgreSQL process-kill recovery, and independently verifiable alert delivery before enabling operational prospective forecasting. To measure paper P&L, independently capture authenticated bid **and** ask plus fees, slippage, financing, positions and order/fill timestamps; do not use historical BID bars as executable prices. Require a tested restore, rollback and health checks before deployment.


## Fail-closed issuance chronology cross-check (28 October 2026)

The disconnected scorecard now independently checks the caller-declared
`maxLagSeconds` (integer 0–3600) and each forecast's completed-candle
issuance window. A base candle must have a nonnegative, UTC-duration-aligned
start; issuance must be at or after its close, strictly before the following
candle's close, and no later than the declared maximum receipt lag. The
target candle arithmetic and 2^53−1 epoch bounds are also checked. This
defends against fabricated or malformed scorecard input bypassing the
validated event-store loader; it does **not** authenticate the caller,
source, clock, event signatures or actual receipt timestamps.

Fourteen additional synthetic parameterized cases cover invalid lag
declarations, pre-close, stale, misaligned and overflowed timestamps,
and an allowed late-within-window issuance. The guard does not infer
unissued forecasts, provider gaps or broker fills. Do not use its passing
status to enable alerts or live trading. All release gates above remain.


## Settlement chronology cross-check (28 October 2026)

The disconnected scorecard additionally rejects caller-declared **SETTLED**
outcomes timestamped before the end of their own target candle, including
multi-candle horizons. Settled and gap-void receipt timestamps must be
non-boolean integers within the bounded 2^53−1 epoch representation.
A `VOID_GAP` may legitimately be recorded before a later target closes
when an intervening source gap invalidates it; that state is not subject to
the settled-target-close lower bound.

These checks do **not** prove the target close price, independently authenticate
the journal, or establish the event-store receipt-lag ceiling; the original
`ForecastEventStore.load` replay remains mandatory. Synthetic tests cover
early and boundary settlement, longer horizons, overflow, and early gap
invalidation. No production alert, paper fill, broker or trading permission
is enabled.


## Opt-in settled target receipt-lag audit (28 October 2026)

`audit_settled_receipt_lag(snapshot)` is a disconnected, read-only
**consistency diagnostic**, not a new mandatory scorecard gate. It validates
the input with the existing scorecard and then counts declared `SETTLED`
receipts later than `targetStart + candleSeconds + maxLagSeconds`.
The deadline is inclusive. It reports the number of late receipts and
largest declared excess, while all source-authentication, notification,
paper and live-execution permissions remain false.

A real `ForecastEventStore._replay` can only settle from a completed
target candle received by that deadline. However, the separate
**synthetic temporal-calibration sensitivity tests** deliberately move
settlement timestamps past cutoffs to study missingness; enforcing this
as a mandatory scorecard rejection would invalidate those existing
analytical cohorts. The audit therefore makes the discrepancy visible
without silently changing their denominator or performance results.

`VOID_GAP` receipts are excluded: a later observed candle can reveal
a missing target after the expected close, and this audit cannot
authenticate market sessions, holidays or feed completeness. The
journal's original replay is still mandatory for real stored records.
Nine synthetic cases cover 1/3/12-candle horizons, inclusive and
one-second-late boundaries, void exceptions, empty and malformed
inputs. No notification or broker capability is activated.


### Model/horizon settlement-lag breakdown (28 October 2026)

The opt-in `audit_settled_receipt_lag(snapshot)` now also returns
`byModelHorizon`, sorted by frozen `modelVersion` and `horizonCandles`.
Each nonempty settled group reports `settledCount`,
`lateBeyondDeclaredLagCount`, `lateFractionOfSettled`, and
`largestExcessSeconds` (null if no violations). Counts reconcile exactly
to the existing aggregate settled and late counters. This prevents an
aggregate pass/fail count from concealing a late-receipt problem limited
to one forecast model or to 1-, 3-, or 12-candle horizons. Groups without
settled outcomes are absent rather than assigned a fabricated zero-rate
observation. `PENDING` and `VOID_GAP` are excluded from the settled-only
denominator, not treated as successful on-time receipts.

These values describe **caller-declared unauthenticated journal times**.
They are not independent provider receipts, feed-uptime evidence, proof
of alert delivery, forward accuracy, or trade profitability. They do
not authorize any notification, paper fill or live order. Three synthetic
regressions cover cross-model/horizon reconciliation, empty/on-time
groups, and fail-closed forged issuance linkage.


### Declared target-close receipt-delay distribution (28 October 2026)

The same disconnected audit additionally reports integer
`receiptDelaySecondsP50` and `receiptDelaySecondsP95` both in aggregate and
for each nonempty model/horizon group. Delays are measured from the *declared*
target candle close to the *declared* `SETTLED.resolvedAt`, in seconds. They
use the deterministic nearest-rank definition (sort all settled delays,
select rank ceil(0.50*n) or ceil(0.95*n), one-based). A zero-settled
population returns null values; `PENDING` and `VOID_GAP` are excluded.
Late settled receipts remain included rather than being conveniently censored.
This makes deteriorating declared timeliness visible even when the maximum
receipt-lag violation count is still zero. Small groups have unstable
percentiles, so no significance or service-level compliance is inferred.

These are *not independently measured provider latency, live candle receipts,
delivery guarantees, tradable quote freshness or trading returns*. The
existing authentication, alert, paper, live-execution and deployment gates
remain closed. Four synthetic regressions cover exact nearest-rank behavior,
status exclusion, empty populations and late-receipt inclusion.
