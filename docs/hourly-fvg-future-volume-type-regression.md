# Future timestamp cannot reclassify volume provenance

The synthetic regression `frontend/tests/hourly-fvg-future-volume-type-mutation.test.ts` supplies a BID-only completed prefix whose declared `volumeType` is `unverified`. The first unrevealed future candle's `time` accessor attempts to rewrite the source declaration to `exchange`. The as-of scanner must fail with the source-declaration snapshot-integrity error; it must not read the future candle's OHLC, volume or minute-coverage fields.

This protects against retroactive promotion of a source classification during a historical as-of scan. A separate verification flag is not a volume receipt. The test cannot verify an actual exchange provider, license, archive identity, broker quotes, or strategy profitability. Retain research-only and paper-only restrictions until independent source and execution evidence exists.
