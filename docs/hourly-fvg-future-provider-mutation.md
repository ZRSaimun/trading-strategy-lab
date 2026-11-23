# Hourly FVG: future-driven provider identity mutation

The causal 1H FVG research snapshot must preserve the exact declared provider identity across all inspected completed and future timestamps. `frontend/tests/hourly-fvg-future-provider-mutation.test.ts` uses synthetic candles and a future **timestamp-only** accessor that tries to replace `fixture-provider` with `another-provider`. The scanner must reject the mutation immediately, before inspecting another future timestamp or any future OHLC, volume or coverage field. The test does not authenticate the source or certify either provider.

This guards one source-provenance integrity boundary, not an executable broker quote, observed volume receipt, or market-data entitlement. The scanner remains BID-only and paper/research-only. Independent broker BID/ASK, source-classified volume, calendar receipts and licensed held-out history are still required for economic evaluation. No win rate or live profitability follows from this synthetic test.

## CI regression repair (21 November 2026)

Workflow [#44940898582](https://github.com/ZRSaimun/trading-strategy-lab/actions/runs/44940898582) failed the frontend job (1 of 1,528 tests) because the test expected `FVG source field changed during declaration snapshot`, whereas the existing fail-closed guard correctly emitted `FVG source declaration field changed during declaration snapshot`. The assertion now matches the implemented error contract; the mutation/no-future-read assertions remain unchanged. This is a test expectation repair, not a weakening of the source identity guard. Recheck exact-head CI before considering the draft reviewed.
