# Causal 1H FVG dataset identity boundary

On 23 November 2026, `frontend/tests/hourly-fvg-future-dataset-identity-boundary.test.ts` added a synthetic regression for a first unrevealed future hourly timestamp accessor that changes the declared `datasetId` while the as-of scanner is validating future timestamps. The scanner must reject the changed source declaration immediately, read that timestamp exactly once, skip the next future timestamp, and never inspect future OHLC, volume or observed-minute coverage. This complements the separate archive SHA-256 mutation test on draft PR #157.

This test only checks source-declaration consistency and no-lookahead accessor ordering. A caller-supplied dataset ID or SHA-256 is not independent proof of licensed provenance, real source-classified volume, executable broker BID/ASK quotes, or trading performance. Keep the PR draft and paper-only; confirm exact-head CI before treating the regression as verified. No live orders or deployment are authorized.

## Stable-declaration positive control

A companion synthetic regression now requires the as-of scanner to accept an unchanged dataset identity while reading exactly three future timestamps once each, without reading future price, volume, or coverage fields. This checks that the mutation guard does not accidentally reject ordinary stable source declarations. It does not authenticate the declared ID or establish market performance. Exact-head CI must be checked separately.

## Second-future-hour mutation short circuit

A further synthetic regression changes `datasetId` on the second unrevealed future hourly timestamp. The causal scanner must read only the first two timestamps once each, never the third, and never access unrevealed OHLC, volume or coverage. This tests immediate fail-closed source identity consistency rather than data authenticity. The new exact-head CI result must be verified separately; no trading outcomes or broker fills are inferred.
