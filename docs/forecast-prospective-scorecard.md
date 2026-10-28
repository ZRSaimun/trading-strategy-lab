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


## Settled target receipt-lag ceiling (28 October 2026)

The disconnected scorecard now additionally rejects a caller-declared
`SETTLED` outcome whose `resolvedAt` is **later than**
`targetStart + candleSeconds + maxLagSeconds`. A target candle can only
settle in `ForecastEventStore._replay` when its completed-candle receipt
arrives by that same deadline; accepting later scorecard-only timestamps
would misrepresent replay eligibility. The deadline is inclusive. This
is a defensive cross-check of an already loaded snapshot, **not** proof
of the source clock, candle finality, or real-time market observation.

A `VOID_GAP` outcome is intentionally **not** subject to the target
receipt-lag ceiling: a later completed candle can reveal that the target
was skipped, and this scorecard cannot independently infer exchange
sessions, holidays or source completeness. The original
`ForecastEventStore.load` replay remains mandatory.

Seven additional synthetic parameterized regressions cover 1-, 3- and
12-candle horizons, zero and maximum declared lag, inclusive deadline,
one-second-late rejection, and a late gap-void exception. No notification,
paper execution, broker order, feed entitlement, or production setting
changes. Keep release gates in place.
