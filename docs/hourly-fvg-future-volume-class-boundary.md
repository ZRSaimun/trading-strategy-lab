# Future-only timestamp volume-class boundary

The synthetic regression in `frontend/tests/hourly-fvg-future-volume-class-boundary.test.ts` checks that the causal 1H FVG as-of scan rejects a source declaration that changes from `volumeType: 'tick'` to `volumeType: 'exchange'` while reading the first unrevealed future timestamp. It must not read a second future timestamp or any future OHLC, volume, or minute-coverage fields. This complements `volumeVerified` mutation tests: classification and verification are separate source assertions, neither of which may be rewritten by future-only data.

The fixture contains artificial prices and adversarial JavaScript getters. A passing test proves only the scanner's local snapshot invariant. It does not authenticate a tick or exchange-volume provider, provide source receipts, verify prior-20 volume, establish broker BID/ASK costs, or demonstrate trading performance. Keep draft, paper-only, unmerged, and undeployed pending independent authorized evidence and review.

The complementary synthetic regression also rejects a `exchange` → `tick` source-class downgrade triggered by the first unrevealed timestamp. It requires one timestamp read, zero subsequent timestamp reads, and zero unrevealed OHLC/volume/coverage accesses. Both directions are integrity checks only; neither source class is authenticated by these fixtures.

CI repair (23 November 2026): the prior test incorrectly used `real`, which is not a supported `FvgSource.volumeType` value (`exchange | tick | none | unverified`). The fixture now uses `exchange` for the purported source class and tests both directions against `tick`. This fixes a TypeScript build failure and a false test failure caused by preflight rejecting the invalid fixture before the future timestamp could be read. A successful CI run is required before considering this repair verified.

Positive control (23 November 2026): a stable `exchange` source declaration with `volumeVerified: false` must permit the causal as-of scanner to read exactly three future timestamps, without reading any future price, volume, or minute-coverage field. This tests against over-rejection from the mutation guard; the synthetic exchange label is not independently verified volume evidence. CI verification is pending for this change.

## Second future timestamp downgrade regression

The synthetic `exchange` → `tick` mutation on the second unrevealed hourly timestamp must fail closed after exactly two timestamp reads. The third timestamp and every future OHLC, volume, and coverage accessor remain unread. This tests declaration consistency and causal isolation only; it does not verify real exchange-volume provenance or strategy profitability.
