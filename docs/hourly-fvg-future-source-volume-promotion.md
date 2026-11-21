# As-of source verification promotion regression

The synthetic regression `frontend/tests/hourly-fvg-future-source-volume-promotion.test.ts`
asserts that an unrevealed future hourly timestamp accessor cannot change the
frozen source declaration's `volumeVerified` flag from `false` to `true`.
The causal as-of scanner must raise the specific source-declaration snapshot
integrity error after exactly one future timestamp read, without reading future
OHLC, volume or minute-coverage fields.

This guards against retroactive evidence promotion, not against dishonest
initial source metadata. `volumeVerified: true` alone is **not** an independently
authenticated volume receipt. Actual provider identities, source-classified
prior-20 volume, licensed historical data and two-sided broker demo quotes
remain required for meaningful empirical validation. No execution or
profitability claim follows from this fixture. Keep PR #157 draft and paper-only;
do not merge or deploy without separate approval.
