# Causal 1H FVG: future source-schema injection regression

A synthetic future hourly candle's timestamp getter is permitted to reveal its timestamp for chronological validation, but its OHLC, volume, and observed-minute coverage must remain unread before close. A malicious or accidental timestamp accessor can add an unreviewed key to the source declaration after the completed-prefix preflight.

`frontend/tests/hourly-fvg-future-source-schema-injection.test.ts` verifies that this source schema mutation fails closed with `FVG as-of source declaration schema changed during timestamp scan`. It also checks that the future timestamp is read once, that future market fields are never read, and that unverified volume is not promoted to verified evidence.

This is a synthetic input-integrity regression, not an independent verification of provider identity, licensed source receipts, historical volume, broker BID/ASK execution, trading outcomes, or profitability. Keep the PR draft and paper-only; check CI for the exact commit before claiming this regression is verified.
