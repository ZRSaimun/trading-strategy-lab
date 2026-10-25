# Causal completed-M1 sweep/MSS-proxy/FVG detector — offline research v1

The module backend/app/causal_m1_confluence_detector.py is a **fixed, research-only M1 hypothesis detector**, with a bridge-compatible candidate schema. It is a separate, narrower **M1** protocol, **not** a port of the unmerged 1H sweep study in PR #24 or 4H/15m CRT study in PR #33. These patterns are simplified ICT/CRT proxies, not independently validated market-structure definitions or trade recommendations.

## Predeclared event rules

For one exact instrument/provider/venue/archive_sha256/price_side/horizon_minutes source, supply strictly increasing, minute-aligned, completed M1 OHLC observations. Each candle's 'at' is its UTC **open**; 'observed_through_close_at' must equal the **last candle's close**. The detector never reads beyond this cutoff. It rejects unknown fields, invalid OHLC, zero/nondecimal prices, duplicates and backward clocks. **Any observed timestamp gap resets the warmup and censors active sweeps; market-session minutes are not fabricated.**

1. **Sweep:** After 20 contiguous prior M1 bars, a bullish candle's low strictly pierces the preceding 20-bar low and its close returns strictly inside the preceding high–low range. Bearish is symmetric for the high. A candle piercing **both** extremes is counted as ambiguous and not assigned a direction.
2. **Confirmation:** During the next **1–5 completed M1 candles**, require both a same-direction closing break of the previous three completed candles' high/low (directional MSS **proxy**) and a same-direction three-candle wick fair-value gap (bullish current.low > high[t−2], bearish current.high < low[t−2]). The confirmation is knowable **only at its close**. No signal can be formed on the sweep candle itself. Multiple competing sweeps confirming on the same close raise an error; no retrospective winner selection.
3. **Candidate:** Each unambiguous confirmation yields a deterministic source-bound path ID and the **15 immediately preceding completed M1 candles, including the confirmation candle**, compatible with compile_causal_atr_intents. The candidate has no future next-open entry price, P&L, outcome or trade order. A sweep not confirmed after five fully observed minutes expires; an unfinished sweep remains pending. Observed gaps censor outstanding sweeps.

All numeric thresholds are fixed before outcome inspection: 20 prior bars, 3-bar structure proxy, 2-bar FVG lookback, 5-minute confirmation window. **Do not optimize them on previously inspected history and present the result as a holdout.** If several hypotheses or parameter variants are compared later, account for selection and multiplicity on an independently untouched chronological holdout.

## Integration and integrity boundaries

From the backend Python environment:

    from app.causal_m1_confluence_detector import detect_completed_m1_confluence
    from app.causal_atr_intent_bridge import compile_causal_atr_intents
    from app.frozen_next_open_intent import audit_next_open_intents

    scan = detect_completed_m1_confluence(source, completed_m1, observed_through_close_at)
    # A zero-candidate scan is NOT a successful backtest. Do not invent trades.
    if scan["candidates"]:
        frozen = compile_causal_atr_intents(source, scan["candidates"])
        # Independently timestamp scan snapshot and frozen evidence/manifest hashes
        # BEFORE next-open outcomes. Later, with verified source/holdout:
        review = audit_next_open_intents(frozen["manifest"], complete_outcomes,
                                         frozen["manifest_sha256"])

The snapshot digest binds caller-supplied OHLC/source/policy/cutoff but **does not prove data authenticity, source licensing, UTC interpretation, independent preregistration, complete upstream detection, untouched holdout or actual fills**. The emitted source_authenticated, independently_preregistered, untouched_holdout_verified, executable_quotes_verified and verified_profitability flags remain false. The downstream ATR policy is a 14-true-range *simple average*, not Wilder ATR. If upstream signals overlap, downstream population completeness, simultaneous exposure and risk must be assessed independently; this helper does not reconcile overlap or issue orders.

Do not unlock quarantined HistData archives or use BID-only prices as executable ASK quotes. A complete backtest requires verified rights, original source/timebase, raw candle identity, independently frozen signal population, purged chronological validation/holdout, missing-observation attrition, bid/ask spread, slippage, commission and financing stress. Previous Nasdaq proxy research was negative under illustrative costs; this new detector has **no measured real-history return or verified edge**.

Run 'cd backend && PYTHONPATH=. pytest -q tests/test_causal_m1_confluence_detector.py'. All test prices are **synthetic**. No API route, UI, database migration, provider request, broker connection, paid service, production dataset mutation or real-money order is included.
