# Future-triggered source volume verification revocation

20 November 2026 — synthetic causal 1H FVG regression on draft PR #157.

The completed BID archive declares `volumeType: exchange` and `volumeVerified: true`. An unrevealed future candle's timestamp getter changes `volumeVerified` to `false` while the scanner discovers the completed prefix. The as-of scanner must fail with the **source declaration snapshot-integrity** error, rather than silently reclassifying already-completed evidence. The future candle's OHLC, volume and minute-coverage accessors must never run. This mirrors the existing false-to-true promotion regression and checks the opposite mutation direction.

This deliberately hostile JavaScript fixture is not an authentic exchange-volume receipt. A caller-supplied `volumeVerified: true` does not prove source identity, licensed history, executable two-sided broker quotes, real first-touch fills, or profitability. Remain paper-only; do not merge or deploy without separate approval. Verify all six CI jobs at the exact PR head before claiming success.
