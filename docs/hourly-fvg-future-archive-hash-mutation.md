# Causal FVG archive receipt consistency

`frontend/tests/hourly-fvg-future-archive-hash-mutation.test.ts` exercises an adversarial, synthetic input: the first unrevealed hourly timestamp getter changes the source archive SHA-256 declaration to another syntactically valid hash. The as-of study must reject the changed receipt immediately, without reading the next future timestamp or any unrevealed OHLC, volume, or minute-coverage field.

A valid-looking hash is not proof of the underlying archive's authenticity. This regression only checks that an already-declared completed-prefix archive identity cannot be silently swapped while the scanner inspects future timestamps. It supplies no licensed historical prices, independent provider receipts, two-sided broker quotes, trade results or profitability evidence. Keep this work draft and paper-only pending exact-head CI and review; do not merge or deploy without approval.
