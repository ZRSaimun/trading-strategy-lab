# Future timestamp must not rewrite completed BID price-side evidence

The synthetic regression `frontend/tests/hourly-fvg-future-price-side-mutation.test.ts` passes two completed hourly BID candles and an unrevealed future candle into the causal 1H FVG as-of scanner. The future candle's timestamp getter tries to switch the completed source declaration from `bid` to `ask`. The scanner must raise the source-declaration snapshot-integrity error, with exactly one future timestamp read and no future OHLC, volume, or minute-coverage reads.

A BID-only historical archive cannot become a two-sided quote stream by retroactively changing a declaration. This regression tests a hostile in-memory accessor and does not establish authentic ASK quotes, spreads, slippage, broker financing, licensed volume provenance, market performance, or profitability. Keep this work draft, paper-only, unmerged, and undeployed pending independent evidence and review.

## 20 November 2026 — CI build repair

[Workflow #44763098611](https://github.com/ZRSaimun/trading-strategy-lab/actions/runs/44763098611) passed all 1,503 frontend runtime tests but failed TypeScript compilation (`TS2322`) because the synthetic mutation assigned `ask` directly to a `FvgSource` field statically restricted to `bid`. The test now uses `Object.defineProperty` to simulate the same hostile runtime metadata change without widening the production BID-only type. The existing snapshot-integrity assertion and no-future-market-access assertions remain intact. Exact-head CI for this repair must be checked separately; no passing result is claimed here.
