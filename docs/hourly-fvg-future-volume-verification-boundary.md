# Hourly FVG future volume-verification boundary

The synthetic regression `frontend/tests/hourly-fvg-future-volume-verification-boundary.test.ts` begins with a source declaring tick volume as **unverified**. A getter for the first unrevealed future timestamp changes `volumeVerified` to `true`. The causal as-of study must reject this source declaration mutation immediately, without reading the next future timestamp or any future OHLC, volume or observed-minute coverage.

This guards against retroactively promoting an unverified completed-prefix volume source to verified status during a future-only scan. The test uses artificial prices and deliberately adversarial JavaScript getters. Passing it does **not** authenticate a volume provider, prove the prior-20 volume threshold, establish actual broker BID/ASK execution prices or show profitability. Source-classified receipts, authorized market data, costs and untouched held-out evaluation remain required. Keep paper-only; do not merge or deploy without separate approval.

## Reverse transition regression (23 November 2026)

A second synthetic test starts with `volumeVerified: true` and changes it to `false` from the first unrevealed future timestamp getter. The causal as-of scan must fail immediately, read only that first future timestamp once, and never access the next timestamp or future candle payload. Both directions of a source-verification identity transition are prohibited after the completed-prefix declaration snapshot. This is a source-integrity invariant, not independent proof that the initial `true` declaration was authentic. Real licensed source receipts and two-sided broker quotes remain missing.

## Delayed revocation boundary

A third synthetic regression lets the first unrevealed timestamp retain the original verified-volume declaration, then revokes `volumeVerified` while reading the second future timestamp. The as-of scanner must reject at that second timestamp, must not read a third future timestamp, and must never access unrevealed price, volume or coverage payloads. This tests delayed metadata mutation rather than genuine provider verification. A source declaration is not an authenticated market-data receipt, and passing this regression establishes neither a valid volume filter nor a trading edge.

## Delayed promotion boundary (23 November 2026)

A fourth synthetic regression starts with `volumeVerified: false` and promotes it to `true` only when the **second** unrevealed future timestamp is inspected. The as-of scanner must reject the changed declaration at that timestamp, read exactly the first two future timestamps once, never inspect the third timestamp, and never read unrevealed OHLC, volume or minute coverage. This complements delayed revocation and prevents later future metadata from laundering unverified completed-prefix volume into evidence. It is a synthetic no-lookahead contract, not a real volume-provider receipt, a broker BID/ASK quote or evidence of profitability.

## Third future timestamp promotion boundary (23 November 2026)

The fifth synthetic regression delays the unverified-to-verified declaration mutation until the **third** unrevealed timestamp. The scanner must read exactly three future timestamps, never inspect the fourth, and never access any future OHLC, volume or observed-minute coverage payload. This specifically protects delayed source-declaration changes during timestamp-only as-of scans; it does not independently authenticate a provider or imply a profitable trading edge. Exact-head CI must be checked after this change.

## Stable-declaration positive control (23 November 2026)

A companion synthetic regression supplies three unrevealed hourly timestamps with a stable `volumeVerified: false` declaration. The causal as-of scan must complete without throwing, inspect each future timestamp once, and never access any future OHLC, volume, or coverage. This guards against an overbroad rejection rule: unknown source verification must remain unknown, not become a fabricated PASS or an automatic scanner error. It is not a source-authenticity receipt, nor evidence of strategy returns.
