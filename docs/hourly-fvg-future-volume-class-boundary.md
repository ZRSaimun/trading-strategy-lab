# Future-only timestamp volume-class boundary

The synthetic regression in `frontend/tests/hourly-fvg-future-volume-class-boundary.test.ts` checks that the causal 1H FVG as-of scan rejects a source declaration that changes from `volumeType: 'tick'` to `volumeType: 'real'` while reading the first unrevealed future timestamp. It must not read a second future timestamp or any future OHLC, volume, or minute-coverage fields. This complements `volumeVerified` mutation tests: classification and verification are separate source assertions, neither of which may be rewritten by future-only data.

The fixture contains artificial prices and adversarial JavaScript getters. A passing test proves only the scanner's local snapshot invariant. It does not authenticate a tick or real-volume provider, provide source receipts, verify prior-20 volume, establish broker BID/ASK costs, or demonstrate trading performance. Keep draft, paper-only, unmerged, and undeployed pending independent authorized evidence and review.

The complementary synthetic regression also rejects a `real` → `tick` source-class downgrade triggered by the first unrevealed timestamp. It requires one timestamp read, zero subsequent timestamp reads, and zero unrevealed OHLC/volume/coverage accesses. Both directions are integrity checks only; neither source class is authenticated by these fixtures.
