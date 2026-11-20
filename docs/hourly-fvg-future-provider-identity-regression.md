# As-of provider identity snapshot regression

The synthetic regression `frontend/tests/hourly-fvg-future-provider-identity-mutation.test.ts` asserts that reading the timestamp of an unrevealed future hourly candle cannot retroactively replace the `provider` identity attached to completed BID candles. The causal scanner must raise the source-declaration snapshot-integrity error, reading the future timestamp once but never accessing future OHLC, volume or minute coverage.

This checks **in-memory consistency**, not the authenticity of a provider, a broker entitlement, a source receipt or an archive hash. Both provider names in the test are fabricated fixture identifiers. Real licensed historical data, independently verified provider/source identities, source-classified prior-20 volume and two-sided broker demo quotes remain missing. No profitability, live execution, merge or deployment is authorized.
