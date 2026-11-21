# Future-triggered archive digest substitution

The causal 1H FVG midpoint research scan must preserve the completed-prefix source declaration, including `archiveSha256`. An unrevealed candle timestamp accessor must not be able to substitute a different well-formed 64-character digest after source validation.

`frontend/tests/hourly-fvg-future-archive-digest-mutation.test.ts` supplies synthetic completed bars, then a future timestamp getter that changes the declared archive hash. The scanner must reject the mutation before a second future timestamp or any future OHLC, volume, or minute-coverage getter executes.

This regression tests in-process declaration stability and causal access ordering only. A stable hash is not proof of a licensed source, a verified broker quote, source-classified volume, real transaction costs, held-out returns, or profitability. Keep the draft paper-only; verify exact-head CI before review. No orders or deployment.
