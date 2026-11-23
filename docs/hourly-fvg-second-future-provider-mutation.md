# Second future timestamp provider provenance regression

The causal 1H FVG as-of study must not allow the provider identity of the completed-bar prefix to change while inspecting timestamps of unrevealed candles. `frontend/tests/hourly-fvg-second-future-provider-mutation.test.ts` uses three synthetic future rows. The first future timestamp is stable; reading the second mutates `source.provider`. The study must reject that change before reading the third timestamp or any future OHLC, volume or coverage fields. Expected timestamp read counts are `[1, 1, 0]`, with zero future market-field reads.

This is a deterministic no-lookahead/source-declaration integrity regression only. It does not authenticate provider identities, verify volume classifications, establish actual broker BID/ASK spreads, validate trading returns, or authorize orders or deployment. Keep the existing PR draft and check CI against the exact new head.

## Stable-source positive control

A paired synthetic control keeps the declared provider unchanged while three future timestamp getters are inspected. The as-of study must accept the completed prefix, inspect each future timestamp exactly once, never read future OHLC/volume/coverage accessors, and retain exactly two completed bars. This distinguishes a real provider-declaration mutation from harmless future timestamp inspection. These assertions are source-integrity tests only, not source authentication or trading-outcome evidence.

## First-unrevealed-timestamp boundary regression (22 November 2026)

The companion synthetic regression now also mutates the declared provider during the **first** future timestamp getter. The as-of scanner must reject the mutation immediately: exactly one future timestamp getter is read, no later timestamp is inspected, and no unrevealed OHLC, volume or minute-coverage getter is invoked. Together with the second-future mutation test and the stable-provider control, this checks both the earliest future boundary and later future iteration. These tests establish only software causal/source-declaration integrity; they do not authenticate the provider, exchange volume, broker BID/ASK quotes, market calendars or trading returns. Keep the research paper-only and the PR draft until exact-head CI is verified.

## Last-unrevealed-timestamp boundary regression (22 November 2026)

A further synthetic control mutates `source.provider` only while reading the **third and final** unrevealed future timestamp. All three future timestamps must be read exactly once (`[1, 1, 1]`), the changed declaration must be rejected, and no unrevealed OHLC, volume or minute-coverage accessor may run. This closes the final-iteration boundary of the existing first/second-future checks without claiming any independent provider authentication or market performance. CI must be verified against the exact updated PR head.

## Erased-provider fail-closed regression (22 November 2026)

A synthetic future timestamp getter now clears the declared provider to an empty string. The as-of scanner must reject the changed source declaration immediately, before inspecting another future timestamp or reading any future OHLC, volume, or coverage payload. This checks a missing-identity transition separately from relabeling one nonempty provider as another. It is not a provider-authenticity check and must not be interpreted as market evidence or strategy profitability.

## Runtime-null provider transition (22 November 2026)

A synthetic timestamp getter now replaces the previously valid provider identity with runtime `null`, bypassing TypeScript's static string type. The as-of scanner must fail closed after the first unrevealed timestamp, without touching later timestamps or future OHLC, volume, or coverage. This checks declaration stability, not independent provider authenticity or market profitability.
