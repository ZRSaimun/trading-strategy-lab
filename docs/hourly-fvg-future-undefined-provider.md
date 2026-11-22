# Undefined provider at the first unrevealed hourly timestamp

The causal 1H FVG as-of study must preserve the source provider identity of the completed-bar prefix even when an input is mutated at runtime outside TypeScript's declared types. The synthetic regression `frontend/tests/hourly-fvg-future-undefined-provider.test.ts` changes the provider from a valid string to `undefined` while the first unrevealed future timestamp getter executes.

The expected behavior is immediate rejection with the existing source-declaration mutation error: the first future timestamp getter is read once, the second is never read, and no future OHLC, volume or coverage getter is invoked. This complements the empty-string and runtime-null provider cases without duplicating their tests.

The test establishes only a deterministic no-lookahead and declaration-integrity contract. It does not verify the provider, authenticate volume or broker quotes, establish strategy profitability, or authorize orders, merges or Render deployment. Check the exact-head CI before considering this regression verified.
