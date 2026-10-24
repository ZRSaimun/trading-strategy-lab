# Historical archive quality diagnostics

The authenticated **Historical Archives** chart now shows an explicit **loaded-window-only** quality panel.

For the currently displayed page(s), it reports:
- loaded UTC start and end, aggregate candle count and actual observed source minutes;
- incomplete intraday minute coverage within loaded buckets (1m through 4H only);
- discontinuities and unobserved timeframe positions **between** loaded bars;
- missing/unknown volume and zero-volume placeholders separately;
- invalid price ranges, repeated/out-of-order timestamps and intraday timestamp misalignment.

### What this does NOT claim

- Gap counts are **not missing-trading-bar counts**: normal weekends, market holidays, closures and contract/session changes may explain them. Exchange calendars are not yet implemented.
- Daily, weekly and monthly *session completeness* cannot be established from UTC calendar buckets, so the panel displays **Not assessed** for those timeframes. Month bucket position counts are also withheld because months vary in length.
- When older pages exist, metrics **do not describe the entire imported archive**.
- Bid-only historical OHLC, absent ask prices and volume placeholders cannot confirm executable broker fills, spread, order-flow depth or strategy profitability.
- The panel performs client-side diagnostics; it does not modify any original price data or private database records. API-level source identity and archive permissions remain unchanged.

These checks are a research aid and are not a substitute for exact-source licences, timestamp validation, session-aware data coverage analysis or out-of-sample testing.

Tests: `frontend/tests/archive-quality.test.ts`. Run the repository's existing frontend CI tests and build before merging. Test with a real permitted archive on the intended browser/device before relying on the UI.
