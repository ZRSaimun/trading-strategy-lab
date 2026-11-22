# Second future timestamp provider provenance regression

The causal 1H FVG as-of study must not allow the provider identity of the completed-bar prefix to change while inspecting timestamps of unrevealed candles. `frontend/tests/hourly-fvg-second-future-provider-mutation.test.ts` uses three synthetic future rows. The first future timestamp is stable; reading the second mutates `source.provider`. The study must reject that change before reading the third timestamp or any future OHLC, volume or coverage fields. Expected timestamp read counts are `[1, 1, 0]`, with zero future market-field reads.

This is a deterministic no-lookahead/source-declaration integrity regression only. It does not authenticate provider identities, verify volume classifications, establish actual broker BID/ASK spreads, validate trading returns, or authorize orders or deployment. Keep the existing PR draft and check CI against the exact new head.

## Stable-source positive control

A paired synthetic control keeps the declared provider unchanged while three future timestamp getters are inspected. The as-of study must accept the completed prefix, inspect each future timestamp exactly once, never read future OHLC/volume/coverage accessors, and retain exactly two completed bars. This distinguishes a real provider-declaration mutation from harmless future timestamp inspection. These assertions are source-integrity tests only, not source authentication or trading-outcome evidence.
