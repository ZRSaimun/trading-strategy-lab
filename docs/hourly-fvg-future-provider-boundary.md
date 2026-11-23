# Causal 1H FVG: unrevealed provider identity boundary

This is a synthetic software regression note for draft PR #157, not an authenticated market-data receipt.

The as-of study may inspect unrevealed hourly **timestamps** to distinguish completed from future bars, but must not read unrevealed OHLC, volume or minute-coverage fields. Its BID provider declaration must remain stable throughout the timestamp preflight. A provider change on the **second** unrevealed timestamp must fail immediately: the first two timestamps are read once each, the third is never read, and no future payload accessor executes.

Regression: `frontend/tests/hourly-fvg-future-provider-second-timestamp-boundary.test.ts`. The first-timestamp counterpart is `frontend/tests/hourly-fvg-future-provider-identity-boundary.test.ts`.

These fixtures do not independently verify the provider, volume type, licensed historical archive, broker BID/ASK quotes, actual fills or profitability. The research remains paper-only. Check the exact-head CI before treating the regression as verified.
