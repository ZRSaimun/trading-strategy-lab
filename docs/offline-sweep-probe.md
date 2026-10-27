# Offline source-local sweep/reclaim research probe (experimental)

This disconnected, **read-only** Python probe is intended for privately held HistData ASCII M1 ZIP archives. It does not change the app's APIs, databases, charts, alerts, brokerage adapters, authentication or deployment. It does not read credentials, place paper or real orders, contact a provider or extract the ZIP.

Run from the backend directory with an authorized local archive:

```sh
PYTHONPATH=. python -m app.offline_sweep_probe /private/path/DAT_ARCHIVE.zip
```

One JSON line is produced per archive. Keep the original ZIPs, member data and any provider-restricted results in private storage; never commit archives.

## Fixed, non-optimized research hypothesis

1. Read one flat `DAT_ASCII_*_M1_*.csv` ZIP member as semicolon-separated source-local M1 OHLCV. Require finite positive valid OHLC, nonnegative finite volume and timestamps on exact minute boundaries. Record archive SHA-256 and discontinuity counts. A backwards timestamp (including an apparent daylight-saving change), missing minute or weekend gap starts a new continuity segment. Do not infer UTC or silently fill a missing minute.
2. Aggregate only **complete** 15-observation, quarter-hour-aligned bars inside one continuity segment. Discard partial 15-minute buckets. All lookback, confirmation and entry bars must be consecutive within a segment.
3. Use the previous **16 completed 15-minute bars** to freeze high and low. A bullish sweep pierces the prior low and closes strictly back above it; bearish pierces the prior high and closes strictly back below it. A candle piercing both sides is rejected as ambiguous.
4. Require the **next completed 15-minute candle** to close strictly above the sweep candle high for long, or below the sweep candle low for short. Enter hypothetically at the **following** 15-minute candle's open. Stop at the sweep extreme, take-profit at **2R**. Refuse nonpositive risk and nonpositive target. Do not overlap simulated positions. **Do not inspect the future entry bar to decide whether the completed sweep/confirmation was a signal.** When the following entry observation is absent, in a different continuity segment, not exactly 15 minutes later or inside the split embargo, count the confirmed signal separately as `confirmed_signals_without_observable_entry`; do not invent a fill, count it as a completed trade or reserve a nonexistent position.
5. Simulate up to **16 15-minute candles**. If a candle touches both stop and target, assign the **stop**. If a subsequent continuous source bar **opens adversely beyond the stop**, use that worse observed source open as a hypothetical exit-price proxy rather than falsely crediting an exact -1R stop. This proxy is not an executable quote, a guaranteed fill, or a worst-case slippage bound; real losses could be larger. If neither is touched by the fixed horizon, use the final observed close. If a continuity gap or split boundary prevents observing a complete outcome, mark the opportunity censored, not a win or loss. **Reserve the entire 16-bar hypothetical holding horizon after any censored entry**, rather than immediately admitting a second signal before the unknown exit. This is a conservative non-overlap convention, **not** proof that an actual broker position would have closed after a gap; any true exposure would require independent reconciliation.
6. Use a fixed chronological **70/30** bar-index split with **16-bar embargo** around the boundary. This is *exploratory later-period comparison*, **not** an independently sealed untouched holdout. No tuning, threshold search, candidate optimization or retrospective outcome-based filtering.
7. Apply additional round-trip **0/5/10/20 basis-point** notional-price deductions to the same frozen hypothetical fills, expressed in units of original stop distance (R). This is **not** measured spread, slippage, commissions, financing, CFD margin, cashflow, bid/ask executable fills or actual position sizing.

The change from protocol `source-local-sweep-confirmation-v1` to **v2** changes the stop-gap return model; all historical return summaries from v1, and summaries from before the censored-position reservation correction, are **stale** and must not be presented as v2 backtests. No private archives were rerun by this code change.

Output contains per-period completed hypothetical trade count, post-entry censored count, **confirmed signals lacking an observable/admissible entry** (`confirmed_signals_without_observable_entry`), arithmetic mean net R and strictly-positive net-return count for each illustrative cost scenario. The entry-observability census closes a selection-accounting blind spot: previously the future entry bar was included in the signal-window continuity filter, silently discarding confirmed signals at gaps and the archive end. Entry-unobservable signals have no demonstrated exposure, so they are not conflated with entered-but-censored positions. Neither group contributes a manufactured return. Censored opportunities are not silently included in performance statistics; they are explicitly counted. Sparse or biased censoring may still distort the reported sample. There are no probabilities, confidence intervals or validated signals.

### Frozen-cohort additional-cost break-even (descriptive only)

For each cohort of **uncensored** hypothetical trades, the report now also exposes `uncensored_mean_gross_r`, `mean_r_cost_per_additional_bps`, and `positive_mean_break_even_additional_bps`. With entry price `p_i`, stop distance `d_i > 0`, and gross hypothetical outcome `R_i`, the same frozen trades obey

`mean_net_R(b) = sum(R_i)/N - b * sum(abs(p_i)/d_i)/(10000*N)`

for an additional round-trip cost `b` in basis points. When `sum(R_i) > 0`, the positive-mean zero crossing is `10000 * sum(R_i) / sum(abs(p_i)/d_i)` bps; otherwise the field is `null`, as it is for an empty cohort. The calculation uses Decimal arithmetic and does **not** choose or filter trades, alter exits, or establish an executable cost allowance. In particular, censored trades are omitted, the source is not authenticated, the later cohort is already inspected, and the cost model excludes measured bid/ask spread, slippage, financing and other broker liabilities. Do not treat a positive threshold as a profitable strategy or an order authorization.

## Safety and interpretation

- HistData ZIP filenames and hashes do **not** authenticate venue, provider rights, account identity, quote side, price correctness or the timezone convention. The file-order split is not a verified market-calendar split. Source-local daylight-saving discontinuities are quarantined by segment.
- BID-only or unverified-side OHLC cannot establish executable long/short CFD entry, spread, stop, target, funding or exit prices. The additional bps are sensitivity tests only; even 20 bps is not a defensible worst-case execution bound.
- The fixed rule is a minimal **liquidity-sweep plus next-candle structure confirmation approximation**. It is **not** a complete or verified ICT/CRT methodology, order-block/FVG detector or profitable model.
- The later period is already inspected in exploratory development. Any future independent performance claim needs new source-authenticated, preregistered, independently untouched chronological observations and realistic broker-side costs.
- `source_authenticated`, `timezone_verified`, `untouched_holdout_verified`, `executable_broker_costs`, `verified_profitability` and `may_execute_order` are always false.
- Never use this probe to execute real-money orders. Any later live integration requires a supported eligible scoped account, fresh executable quote, independent hard risk limits and explicit owner approval **for each order**.

Tests: `PYTHONPATH=. pytest -q tests/test_offline_sweep_probe.py` from `backend/`. All fixtures are synthetic; no proprietary historical data or credentials are checked in.


## v3: causal confirmation boundary and full signal-attrition census

Protocol `source-local-sweep-confirmation-v3` excludes a development
sweep whose **confirmation** falls inside the chronological embargo; v2 could
inspect that embargo confirmation before recording an unobservable entry.
All earlier v1/v2 exploratory returns are **stale** under this changed
population rule and must be rerun on authorized source archives. The
already-inspected later slices are never independent holdouts.

Every *admitted, completed-confirmation* signal is counted exactly once in
`confirmed_signals`, and must satisfy both exact identities:

`confirmed_signals = confirmed_signals_without_observable_entry + invalid_entry_stop_or_target_geometry + entered_positions`

`entered_positions = observed_outcomes + censored_due_to_gaps_or_boundaries`

`unresolved_or_unadmitted_signals = confirmed_signals - observed_outcomes`.
`all_confirmed_signals_resolved` is true only for a nonempty cohort with
no missing entry, invalid entry risk/target geometry, or censored outcome.
The mean-R and cost break-even statistics **still apply only to observed
entered outcomes**. These counts disclose potential selection bias; they
do not impute missing outcomes, bound adverse gap losses, establish
statistical significance or make incomplete samples representative.
In particular, no amount of zero observed censoring authenticates source
rights, timezone, executable costs, or holdout independence.

The census is *capacity-admitted* (non-overlapping) signals only, not a
claim about every market pattern during an already-open simulated trade.


## Entered-position missing-exit loss stress (additive v3 diagnostic)

The v3 report now includes `censored_entered_loss_stress_scenarios` for each
chronological cohort. These **illustrative counterfactuals** address the
selection risk of calculating mean returns only on observable exits. For
each already-entered, censored hypothetical position, the scenario assumes
a loss of **-1R, -3R, or -5R**, and deducts the same additional **0, 5, 10,
or 20 basis-point** round-trip notional cost from *all* entered positions,
including censored ones. The mean uses the complete **entered-position**
denominator, not just the observed exits. The 12 scenarios do not change
signals, entry/stop geometry, actual observed outcomes, capacity admission,
the chronological split, or the existing observed-only statistics.

The arithmetic is

`stressed_mean_R(b,L) = [sum(observed_gross_R) - L * N_censored - (b/10000) * sum(all_entered_abs_entry/stop_distance)] / N_entered`

where `L` is 1, 3 or 5, and `b` is the *additional hypothetical* round-trip
cost in bps. All arithmetic uses Decimal and remains undefined (`null`)
when there are no entered positions. The result explicitly labels itself
`ILLUSTRATIVE_MISSING_EXIT_STRESS_NOT_A_LOWER_BOUND`.

**These scenarios are not finite worst-case loss bounds.** A missing exit
may be much worse than -5R, especially through a gap, and actual CFD
financing, bid/ask spreads, commissions, FX and slippage are unverified.
Signals lacking an observable entry and signals with invalid stop/target
geometry are **excluded** from this entered-position stress because their
entry price or admissible risk is not known; their separate census fields
remain visible. A zero-censor cohort yields the same mean as the original
observed-only cost scenario. These are research sensitivity calculations,
not broker fills, position-sizing rules, a confidence interval, evidence
of positive expectancy, or permission to trade. The already-inspected
historical later periods remain development-only.


## Observed exit-path census and source-open stop-gap severity (v3 additive)

Each frozen cohort now reports `observed_exit_path_census`. Every **observed**
hypothetical outcome is assigned exactly one source-OHLC exit path:
`stop_touch_without_adverse_open`, `stop_touch_with_adverse_open`,
`target_touch`, or `horizon_close`. The four counts must sum to
`observed_outcomes_total`, which equals `observed_outcomes`.
An entered-but-censored position is **not** assigned an observed exit.

For a source candle opening adversely beyond the stop and also touching
the stop, the model already uses the adverse source open as a stop-exit
proxy. The new `adverse_source_open_extra_loss_r_sum` is the sum of
`abs(source_open - stop) / original_stop_distance` over those events,
i.e. the **extra** modeled loss beyond a hypothetical exact -1R stop.
`adverse_source_open_extra_loss_r_max` is the largest such extra modeled
loss, or `null` when there are no adverse-source-open stop events.
These statistics do **not** alter entry selection, exits, cost scenarios,
missing-outcome stress, chronological boundaries, or the observed returns.

A 3.6R extra source-open loss means the stop-path proxy is -4.6R before
additional costs; it is **not** evidence that a broker would execute at
that open. Source-local OHLC cannot establish real gaps, spread, slippage,
liquidity or the maximum adverse fill. The diagnostic is not a finite
worst-case bound, a probability estimate, a strategy selection criterion,
or a live-order permission. Do not compare or tune candidate strategies
against the already-inspected exploratory later periods as if untouched.
