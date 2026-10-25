# Native Gold CSV research

The private server's **Gold CSV Research** page accepts original UTC XAU-USD
Dukascopy-format `1Hour` and `1Min` BID or ASK CSV exports. It saves datasets
separately by filename and content hash in the existing private `records` table,
then provides a native-timeframe candlestick chart and candle-by-candle replay.
Refresh and select the saved dataset to reopen it. Static GitHub Pages reports
that this feature requires the private deployment.

Use the original filename pattern:
`XAU-USD_1Hour_BID_2026-09-01_to_2026-10-01_Etc_UTC.csv`.
Accepted headers: `Etc/UTC,Open,High,Low,Close,Volume`.
The end date is inclusive; actual candle coverage is displayed. Filenames and
user declarations do not authenticate a vendor or prove the actual bar duration.
Do not rename another instrument or timeframe to bypass validation.

Limits: 1 MB / 5,000 bars per file. Export shorter windows for M1 files.
Validation rejects empty data, extra/missing columns, non-UTC or misaligned
stamps, duplicate/disordered timestamps, future/incomplete candles, invalid
OHLC/volume, and rows outside the declared dates. Identical reuploads are
idempotent. Each new dataset creates an audit event. Existing minute charts,
strategy data, and historical ZIP archives are not replaced. Back up the
private database's records table to retain these datasets.

All endpoints require the existing owner session and application origin guard:
- `POST /api/gold-csv`: multipart file and rights_confirmed.
- `GET /api/gold-csv`: metadata inventory.
- `GET /api/gold-csv/{id}`: native candles and observed-gap diagnostics.

Research limitations:
- H1 observations cannot be expanded into M1/M5 prices or supplied to minute
  backtests. This page does not trigger strategies, alerts or orders.
- BID and ASK sources are isolated. Independent OHLC extrema are not
  simultaneous quotes and cannot establish a spread distribution.
- Volume remains unclassified, even when nonzero. No volume confirmation or
  exchange-volume claim is made.
- Gap counts include closures and missing observations; no session calendar
  completeness is assumed and no prices are filled in.
- Source authenticity, broker equivalence and data-use permissions require
  independent verification. This is historical research, never a live feed.

Original user exports and research databases must remain private and outside
Git. The implementation contains no user candle data. Tests use synthetic fixtures.
