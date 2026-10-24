# Archive-backed research backtests

The **Backtesting** screen on an authenticated private deployment can now use the same completed, source-isolated historical ZIP datasets shown in **Historical Archives**.

1. Import and verify a licensed archive using the existing offline ingestion workflow (see `resumable-histdata-import.md`). No ZIP uploads are made by the backtester.
2. Open **Backtesting → Historical data source → Imported historical ZIP archive**.
3. Select a READY archive by its exact instrument/provider/format and short dataset identity. Pick a supported timeframe (1m, 5m, 15m or 1H).
4. Set meaningful hypothetical costs, point value and risk parameters; run the five research approximations.
5. Review the recorded start/end, archive SHA-256, excluded incomplete aggregates, 60/20/20 chronological splits, trades and explicit capped-window warning. Export a reproducible report if desired.

## Safety and reproducibility

- Pages are fetched through authenticated, read-only `/api/history/{dataset_id}/candles` requests.
- A run accepts **only one immutable archive dataset identity**. Hash/identity changes, repeated or unordered candle timestamps, malformed cursors and unexpected live-price claims reject the run.
- The browser loads at most **20,000 aggregated bars**, in pages of at most **2,000**. A run may cover only the most recent portion of the selected file; the warning is not proof that the whole archive was tested.
- Complete one-minute constituent coverage is required for each aggregate used by the existing research simulator. Incomplete aggregates are excluded; missing intervals remain gaps rather than invented prices.
- Imported historical data is **BID-only**, with no historical executable ask, live spread, broker financing, exchange microstructure or verified fills. User-configured costs are assumptions. This is not a live strategy signal or proof of profit.
- Saved reports remain subject to existing storage size limits. If a large report cannot be saved, export a JSON file and keep it private.
- Different ZIPs, futures expiries, proxy symbols, quote sides, providers or archive files are **not silently combined** into long continuous series.
- Fixed 60/20/20 splits do not by themselves create a genuinely unseen holdout when repeatedly inspected or optimized; use forward paper validation and independent fresh data before trusting a strategy.

This feature does **not** import the owner's full private dataset into Render, modify stored data, schedule cloud workers or enable broker orders. The server must already have the archive migration/data installed. GitHub Pages remains browser-local and does not offer server archives.

## Automated checks

`frontend/tests/backtest-history.test.ts` covers sorted-page assembly, bounded windows, archive identity/hash preservation, overlap rejection, cursor validation and the refusal to treat live/malformed responses as backtest history.

## Legacy chart pagination boundary

The older authenticated `GET /api/candles/{instrument}` endpoint accepts an optional
`before` cursor. This is a **raw minute timestamp cutoff**, not an offset
within an aggregated candle. The cursor must equal the UTC start of a full
requested timeframe bucket (for example, 10:00 UTC for `1H`, Monday 00:00 UTC
for `1W`, or the first day of a UTC month for `1M`). The API now returns
HTTP 422 for negative, out-of-range, or non-aligned cursors rather than
silently calculating a misleading partial OHLC aggregate.

To page backward safely, use the `time` of the **oldest returned aggregate**
as the next `before` value; the endpoint uses a strict less-than cutoff.
The endpoint still returns at most 2,000 aggregates and is not an
unbounded multi-year backtest feed. This fix does not fill gaps or change
the archive-backed `/api/history/{dataset_id}/candles` endpoint, which
already validates aligned cursors.
