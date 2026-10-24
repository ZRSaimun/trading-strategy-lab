# Same-close sweep / structure-break / FVG confluence — research only

This independent, pure TypeScript research helper lives at `frontend/lib/sweep-confluence-study.ts` and has no broker, order, database, or network calls. Its deliberately **predeclared** `sweep-mss-fvg-same-close-v1` hypothesis asks whether a v3 liquidity sweep followed within three completed 1H candles by a directional structure break **and** directional three-candle FVG at the same completed close has positive three-hour directional follow-through. A structure break is only a **proxy** for MSS, not a validated MSS/CHOCH, CRT setup, retest or executable signal.

The sweep is detected at its completed close. Only causal v3 observations whose reference candles are in the same complete, contiguous source segment are accepted. The earliest qualifying confirmation candle is selected independently of future price; one confirmation cannot be reused by multiple sweeps. Entry is assumed at the **next** candle open; exit is at the close of the third bar after confirmation. Any missing, partial, out-of-order or gap-spanning candles fail closed. Results use the sign of the directional bid-price move and subtract three explicitly hypothetical *round-trip* cost scenarios: 0, 5 and 15 basis points. These are **not** verified spread, slippage, commission, CFD financing, margin, broker contract, or fill models. No stops or targets are modeled. Missing outcomes remain pending or excluded; they are not counted as wins/losses.

## Retrospective 24 October 2026 source-isolated diagnostic

The owner-provided local SQLite research copy was opened read-only. Each of 26 READY **ASCII** HistData archives was aggregated separately from minute rows to hourly OHLC, with observed minute counts. No across-archive stitching or interpolation was performed. The separate Gold MetaTrader duplicate was deliberately not pooled with the Gold ASCII file. HistData's fixed -300-minute UTC source offset was declared in the database; the original quotes and their broker execution properties were not independently authenticated. SHA identities and source metadata remain in the private local report, not in the public repository.

| Source | ASCII archives | Hourly buckets | v3 sweeps | Strict confirmations | Complete outcomes | Mean net 5 bps | Mean net 15 bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nasdaq CFD proxy NSXUSD | 20 | 63,130 | 3,088 | 84 | 69 | -4.04 bps | -14.04 bps |
| WTI CFD proxy | 5 | 1,813 | 95 | 0 | 0 | N/A | N/A |
| Gold OTC proxy | 1 | 271 | 15 | 0 | 0 | N/A | N/A |

The Nasdaq average **gross** directional outcome across 69 completed observations was +0.96 bps. Only 43.5% of those outcomes were positive after 5 bps assumed costs. There is **no verified positive edge**, and the sample is sparse and clustered. These figures are retrospective and the same historical archives have been studied before, so they are not independent validation or untouched holdouts. Overlapping events and source-specific sample lengths limit inference. No live broker prices, paper fills or production deployment were involved.

The private local report `confluence_all_archives_20261024.json` includes per-archive counts, assumptions, SHA source identity and means. Do not commit licensed raw candles, original archives, API secrets or the private SQLite database.

## Reproduce / verification

Run `node --experimental-strip-types --test tests/sweep-confluence-study.test.ts` from `frontend` and `npm run typecheck`, followed by full frontend/backend/Docker/cloud CI on the PR. The eight synthetic tests cover next-open causality, cost scenarios, same-close and directional constraints, fixed confirmation deadline, gap/incomplete data rejection, one-to-one confirmation use, invalid provenance, order invariance and pending outcomes. They validate software behavior, not profitable trading. The diagnostic used a read-only local research copy, not a production database.

## Handoff

Next research: freeze complete entry/stop/target/invalidation and capital-risk rules, then evaluate new independently arriving source-identified quotes with measured bid/ask spreads and actual paper fills. Do not use this exploratory 69-observation result to optimize the confirmation window, exit horizon or costs retrospectively. Keep any future broker integration separately permissioned, with owner confirmation per real-money order and a durable kill switch. Trading 212 CFD orders remain unsupported by its documented Public API.
