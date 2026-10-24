# Completed-candle structure observation safeguards (v2)

This research-only patch addresses two false-pattern classes in the Research Charts / replay observation engine. It does **not** create a trade signal or establish profitable performance.

## Ambiguous double-sided sweeps

A candle can wick below a confirmed swing low and above a confirmed swing high while closing back inside both levels. Previously the chart emitted contradictory bullish and bearish sweep observations for that same candle. The detector now emits **neither** directional sweep observation in that situation. A single-side reclaim still emits an observation only after its candle closes. Structure breaks are unchanged. The swing remains confirmed only after the required right-side candles have closed.

## Three-candle FVG data quality

A bullish/bearish three-candle wick gap is now emitted only if all three candle timestamps are adjacent in the requested timeframe and their observed-minute counts are nonzero. For intraday 1m–4H candles, each aggregate must also have the full expected number of one-minute observations. For 1D and 1W, the detector requires adjacent calendar buckets and at least one observed minute; it cannot certify complete trading sessions. For 1M it requires three consecutive UTC calendar months (including year transitions) and nonempty observations. Unknown market closures, sparse archives and partial intraday buckets must not manufacture FVGs. This is conservative: legitimate formations near a missing bar may be suppressed rather than guessed.

The observation rule version changes from `structure-research-v1` to `structure-research-v2` to preserve provenance. Existing historical alert records should not be silently relabeled; they retain the version and data available when generated. No existing imported candles, saved strategies, reports or journal entries are rewritten.

## Tests and limitations

Deterministic regression cases cover two-sided ambiguity, one-sided preservation, gap-spanning FVG suppression, partial aggregate suppression, hourly completeness, UTC monthly rollover and prefix invariance. No proprietary archive data or broker data is committed. No trades, credentials, subscriptions or production database changes. The detector remains descriptive; it does not infer market regime, true MSS/CHOCH, stop placement, transaction costs, spread or forward profit.
