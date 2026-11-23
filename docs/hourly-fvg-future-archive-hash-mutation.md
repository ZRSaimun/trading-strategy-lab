# Causal FVG archive receipt consistency

`frontend/tests/hourly-fvg-future-archive-hash-mutation.test.ts` exercises an adversarial, synthetic input: the first unrevealed hourly timestamp getter changes the source archive SHA-256 declaration to another syntactically valid hash. The as-of study must reject the changed receipt immediately, without reading the next future timestamp or any unrevealed OHLC, volume, or minute-coverage field.

A valid-looking hash is not proof of the underlying archive's authenticity. This regression only checks that an already-declared completed-prefix archive identity cannot be silently swapped while the scanner inspects future timestamps. It supplies no licensed historical prices, independent provider receipts, two-sided broker quotes, trade results or profitability evidence. Keep this work draft and paper-only pending exact-head CI and review; do not merge or deploy without approval.

## Second-future boundary regression (22 November 2026)

A second synthetic case changes the archive SHA-256 while reading the **second** unrevealed timestamp. It requires exactly two future timestamp reads, no third timestamp read, and no future OHLC/volume/coverage access. The mutation is rejected even though the replacement is a syntactically valid SHA-256-shaped string. This is an adversarial software-integrity check, not independent source verification or trading-performance evidence.

## Third-future boundary regression (22 November 2026)

The third unrevealed timestamp getter now mutates the archive receipt while a fourth future timestamp remains unread. The causal study must fail closed after exactly three timestamp reads, without reading the fourth timestamp or any unrevealed OHLC, volume or coverage payload. This checks receipt consistency at another scan boundary; synthetic assertions do not authenticate an archive or demonstrate trading performance.

## Stable-receipt positive control (22 November 2026)

A matching synthetic control supplies four future timestamp getters with a constant archive SHA-256 declaration. The causal as-of scan must accept the stable source identity, read each future timestamp exactly once and never inspect unrevealed OHLC, volume or coverage. This distinguishes mutation rejection from indiscriminate rejection of future timestamps. It does not authenticate the archive or establish a profitable trading edge.
