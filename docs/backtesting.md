# Historical backtesting and demo research journal (v0.3)

Open Backtesting, choose the exact imported instrument and timeframe, enter realistic source-specific cost assumptions and point value, then run all five variants. No market data is bundled. At least 100 chart candles are required in the UI; complete one-minute constituents are required in every simulated aggregate candle. The browser limit is 20,000 aggregate bars. A private-server chart request currently returns at most 2,000 bars; the report prominently records when it uses that capped window.

This is a deterministic **research simulator**, not a validated profitable trading system. Rule definitions below are deliberately explicit approximations. In particular A is not claimed to reproduce the owner's original method, and C/D/E are not comprehensive implementations of discretionary CRT/ICT.

## Rule versions

- A, `range-break-v1`: close above/below the previous N-bar high/low, stop at the opposite range extreme. Deliberately a first-break baseline for comparison; it is not the revised rule.
- B, `sweep-shift-retest-v1`: wick outside the prior N-bar range and same-bar reclaim; store the pre-sweep preceding three-bar structure and sweep extreme. A later candle must close beyond that structure with directional body at least displacement × prior ATR; a further candle must touch the broken structure and close on the defended side without hitting the sweep extreme. The candidate becomes eligible only after that retest closes.
- C, `crt-range-v1`: use the previous N closed candles as the CRT reference range; wick sweep and same-bar reclaim gives the candidate. This simplified CRT variant has fewer filters than B.
- D, `fvg-retest-v1`: a three-candle wick FVG plus directional ATR displacement closing through the preceding three-bar extreme; then a later defended retest of the third-candle gap boundary. Stop at the first gap candle's opposite extreme.
- E, `combined-research-v1`: B plus the directional FVG on the structure-shift confirmation bar. No assumption that this wins the comparison.

Reference levels and ATR use only preceding candles. Range high/low are frozen when the pending setup is created. Both-sided sweep candles are rejected as directionally ambiguous. Pending setups expire after the configured number of bars from creation or invalidate at the stop extreme. Unknown time gaps reset pending setups and require fresh contiguous reference windows. There is no contextual higher-timeframe alignment, opposing-liquidity room test, news filter, volume filter, tick-size rounding or full continuation-breakout model yet. The comparison UI states those limits.

## Execution and costs

One hypothetical position per independent strategy. A closed-bar candidate can enter only at the next observed open, and only if there is no time gap and the raw open remains on the valid side of its stop. Buy entries pay half the full spread plus slippage; sells receive the adverse equivalent. Exits pay the same adverse friction. Commission is currency per research unit per side. Point value is currency per one price-point move per research unit; it is not automatically a broker contract multiplier.

Sizing risks configured percent of current closed balance using the stop distance **including** exit friction and round-trip commission. Fractional units are allowed; no margin, leverage, lot increments, liquidity limits or currency conversions are simulated. Targets are computed to meet the configured net RR after modeled costs; this does not prove sufficient real opposing-liquidity room exists.

If a candle touches both stop and target, stop fills first. Stops gapped through fill at the adverse open; favorable target gaps receive no extra improvement. An unknown gap while holding is closed conservatively at the stop or worse observed open, since the missing excursion cannot be reconstructed. Maximum holding period and end-of-sample positions liquidate at close with adverse costs. Exit timestamps for intrabar exits are recorded at the containing candle's close boundary; precise intrabar times are unavailable.

Drawdown is calculated from close-marked liquidation equity including estimated exit costs and commissions. Intrabar drawdown may be larger. Equity curves stored with a saved run are sampled to approximately 500 points per result; metrics are calculated before sampling. Exporting the active run preserves its full curve. Complete trade logs, config, engine/rule versions, original CSV hash, source metadata and actual candle snapshot are saved/exported so simulations can be repeated.

## Comparison, uncertainty and journal

Full sample and fixed chronological 60% development / 20% validation / 20% holdout segments use independent starting capital and no optimization. Each segment has its own warmup and forced end liquidation, so segment returns do not compound into the full run. These splits do not prevent a user from overfitting after repeatedly inspecting holdout results. Automated walk-forward fitting, multiple-testing corrections and overfitting detection are not yet available.

Metrics include closed trades, win rate, profit factor, average win/loss, expectancy, return, net P&L, average R, close-marked drawdown and execution rejections. Win-rate Wilson intervals are displayed with the independence limitation; serially correlated trades reduce their validity. Profit factor is undefined if no losing trades exist and win rate is undefined for zero trades. Zero-trade reports never imply a perfect win rate. Sample-size and cost assumptions remain visible.

Add selected trades to Trading Journal. Entries initially say SIMULATED ONLY and SIMULATED OHLC ONLY. A user can separately mark USER-REPORTED DEMO ENTRY; this never verifies broker fills or transforms modeled P&L into actual P&L. Notes are editable. No broker endpoint exists.

Browser-mode reports/journal live in IndexedDB. The newest 20 reports and 500 journal entries are retained; export important records before saving further entries. A 6 MB per-record limit applies. Private-server mode stores records in the authenticated database and audits changes; the server treats reports as client-supplied research records, not independently verified computations. Journal edits are single-user and do not yet have cross-tab optimistic version checks. Export JSON backups are available; restore UI remains pending.

## Verification

Nine deterministic simulator tests cover next-open eligibility, stop-first ambiguity, net 2R after costs, first-break rejection for B/E, candidate prefix invariance, evidence timestamps, gap entry rejection, raw-open invalidation, reproducibility, undefined zero-sample statistics, final-bar rejection, the positive B shift/retest path and conservative unknown-gap exit. Five prior parser/pattern/replay tests and seven backend authentication/persistence/audit tests also pass. Browser end-to-end interaction remains unverified.
