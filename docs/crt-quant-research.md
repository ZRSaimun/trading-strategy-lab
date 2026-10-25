# Causal 4H CRT and 15m confirmation research (v1)

**Status:** Prototype research screening, **not** an order filter in a broker account or a proven profitable CRT/ICT strategy. Open the authenticated private terminal's **CRT / ICT Research** tab; select one exact imported historical ZIP archive. All original source records remain read-only.

## Frozen test hypotheses

1. **Reference Candle 1:** a completely observed, UTC-aligned 4H bar. **Manipulation Candle 2:** the next adjacent complete 4H bar, with an unambiguous outside-wick excursion past exactly one reference extreme and a close back strictly *within* Candle 1's high/low. Simultaneously sweeping both extremes is excluded. Bullish setup sweeps Candle 1 low; bearish setup sweeps Candle 1 high.
2. **Sweep depth:** excursion outside Candle 1 boundary divided by Candle 1 full high–low range. Reject if greater than the *research parameter* `0.40`. Zero-range references and ambiguous sweeps never become candidates.
3. **15-minute structure-shift proxy:** after Candle 2's **4H close**, inspect the next complete 4H block for the **first** 15m candle whose close breaks the maximum high (bullish) or minimum low (bearish) of its previous three closed 15m bars, with directionally matching open-to-close movement. No future confirmation bar may be used before it closes.
4. **Displacement:** compare that *first* shift candle's full high–low range to the median high–low range of its **20 immediately preceding contiguous, complete 15m bars**. Suggested threshold: at least 1.5×. No second-chance cherry-picking of a later shift if the earliest shift lacks displacement.
5. **Volume:** require verified, non-placeholder exchange/tick volume classification and 20 contiguous positive-volume prior bars. Candidate volume greater than 1.5× their arithmetic mean; otherwise mark `INSUFFICIENT_DATA` when volume is missing/unverified and `FAIL` for known below-threshold volume. HistData unverified or zero-volume placeholders do not count as confirmation.
6. **Daily trend proxy:** compare the last 5 *fully closed and fully observed (1,440-minute)* UTC daily closes to the last 20 such closes; reject counter-directional proxies. To avoid treating stale historical observations as current context, require the most recent qualifying daily close to be **no more than 3 days before** the 4H sweep close and the last 20 qualifying daily closes to span **no more than 30 days**. Otherwise report `INSUFFICIENT_DATA`, not `PASS` or `FAIL`. These are conservative, predeclared research freshness bounds, **not** a verified exchange calendar or an assertion that gaps are weekends/holidays rather than outages. Shortened legitimate sessions may be excluded.
7. **4H supply/demand zone:** only recognize a finite, bounded, source-linked reference whose 4H source candle was fully closed and whose observation timestamp was **no later than the sweep candle opening**. Match the zone to the sweep candle’s **own completed close**, never a later 15m confirmation close. A zone first recorded during the sweep, one referencing the sweep itself, or one matching only a future confirmation price is `INSUFFICIENT_DATA`. This tab does not synthesize an "institutional order block" from arbitrary candles or let unverified zone coordinates authorize trading.
8. **High-impact news:** until an authorized, publication-time-aware calendar with FOMC, NFP, CPI and market-specific high-impact events exists, the 15-minute pre-news rule must remain `INSUFFICIENT_DATA`; no hidden assumption that a given day is free of news.

The 40%/1.5× levels, daily trend proxy and structure-break proxy are **owner-proposed statistical hypotheses**; there is no established 38%→62% improvement, guaranteed RR or certified ICT order block proven by the code. No result in this screen grants broker execution privileges.

## Observability and fail-closed guardrails

- Validate strict OHLC, positive prices, complete aggregate minute coverage, UTC bucket alignment and ascending unique timestamps.
- Fetch 4H, 15m and daily candles from the **same READY archive**, comparing dataset IDs, SHA-256 source content hash, exact provider/instrument and BID-only historical quality on every response.
- The screen selects a **recent API page, up to 2,000 candles per timeframe**; the 4H window is trimmed to the observed 15m coverage to avoid misrepresenting absence of younger confirmation as historical invalidation. API paged history beyond the first 2,000 bars is not evaluated yet.
- Contextual news and zone fields are not externally wired to unverifiable data. The current history import does not supply authenticated exchange volume, so the volume gate stays unavailable in the screen.
- No bid/ask, swaps, broker-specific spread shocks, price-to-currency conversions, lot constraints, capital equity, drawdown, economic releases or order submission is modeled by this diagnostic.
- A future backtest must use independent 4H/15m slices with correct release/closure times, locked holdouts, variable spread assumptions and out-of-sample evaluation. It must not present these counts as actual fills.

## Automated regression testing

`frontend/tests/crt-quant-filters.test.ts` exercises causal 4H-to-15m close alignment, sweep depth over 40%, the frozen first confirmation, 20 contiguous prior-bar displacement, source volume unavailability, completed daily-trend lookback **including stale/sparse historical windows and short closure gaps**, source-specific zone provenance, and invalid historical bars.

Run the project's frontend/backend/Compose CI checks. Test with actual licensed historical imports on the target Render deployment **after separate review and release**, not by committing private market data to public Git history.

## Planned next research work (not yet implemented)

- Causal standalone 1H FVG midpoint rejection screen (wick >= 50% of candle range plus classified above-average volume), compared against a blind limit baseline.
- Incremental 1m/5m/15m versus 1H/4H net-cost analysis, rather than claiming small timeframes always lose.
- Actual broker-specific two-sided CFD quotes, spread and financing schedules, structured high-impact news timestamps, true exchange calendars and contract multipliers.
- Full multi-year cost stress, DSR with multiple-trial corrections, truly untouched holdout, demo-paper forward tests and validated risk circuit breakers.

Existing confluence PR #24 remains a separate 1H sweep/FVG research hypothesis. This branch does not change it, nor any broker APIs or production databases.
