# First future-row mutation: fail-fast causal boundary

The synthetic regression `frontend/tests/hourly-fvg-first-future-mutation-short-circuit.test.ts` checks that the 1H FVG as-of study stops at the **first** unrevealed timestamp if that timestamp accessor retroactively changes the completed source provider declaration. A second unrevealed timestamp accessor is deliberately configured to throw if accessed. The expected outcome is the specific source-snapshot integrity error, exactly one first-future timestamp read, zero second-future timestamp reads, and zero future OHLC, volume or minute-coverage reads.

This is a regression for short-circuit ordering, not a source-authentication receipt. The synthetic provider and candles are invented software fixtures, not historical market prices. Unverified volume remains unverified. No result establishes a fill, tradable price, strategy edge or profitability. The experiment remains paper-only and does not permit broker orders, deployment or use of private datasets in public GitHub.

## CI repair — 21 November 2026

Exact-head workflow #44843931191 failed frontend `npm test` (1 failed of 1,512) because the as-of scan deferred source declaration revalidation until after all future timestamps. The second future timestamp getter executed before the source-integrity error. The implementation now checks the frozen source declaration immediately after each permitted timestamp read, before advancing to another row. This is a fail-fast causal integrity fix; the existing regression remains the acceptance test. New-head CI must be checked separately; the failing workflow is not evidence of a pass.
