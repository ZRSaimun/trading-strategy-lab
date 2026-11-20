# Future-triggered volume classification downgrade regression

20 November 2026 — draft PR #157, synthetic causal 1H FVG evidence-integrity regression.

A completed BID source declares `volumeType: exchange` and `volumeVerified: true`. An unrevealed future candle timestamp accessor changes the completed source declaration's volume type to `unverified` during causal prefix discovery. The scanner must reject this with the specific source declaration snapshot-integrity error, without reading the future candle's OHLC, volume or minute coverage. This complements the existing unverified-to-exchange promotion test and the independent verification-flag revocation test.

A synthetic source declaration, even with `volumeVerified: true`, does not authenticate exchange volume or provider identity. This regression is not broker BID/ASK evidence, a fill simulation, licensed held-out history or evidence of trading profitability. Keep paper-only, draft, unmerged and undeployed; confirm exact-head CI separately.
