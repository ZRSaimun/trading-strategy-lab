# Research chart studies — v0.8

These studies run on authorized imported candles in Research Charts, independently of the remote Market Charts display. Open Indicators, then select individual overlays or panes. All studies default off to avoid chart clutter. Current fixed presets:

| Study | Formula and first output |
|---|---|
| SMA 20 | Arithmetic mean of the last 20 observed closes; candle 20 |
| EMA 20 | Seed with first 20-close SMA, then alpha 2/21; candle 20 |
| Bollinger 20 | SMA 20 ± twice population standard deviation of last 20 closes; candle 20 |
| VWAP | Cumulative (high+low+close)/3 weighted by supplied volume, reset at Europe/London midnight, including DST |
| RSI 14 | Wilder average gains/losses of close changes; candle 15. No losses = 100; no gains = 0; flat = 50 |
| ATR 14 | Wilder average true range; first true range is high−low, later ranges include previous-close gaps; candle 14 |
| MACD | SMA-seeded EMA12 − EMA26; candle 26. Signal is SMA-seeded EMA9 of MACD; candle 34. Histogram = MACD−signal |
| Volume | Source-provided nonnegative volume, explicitly labelled tick or exchange |

Warmup periods are whitespace, never zeros. No future candles, centered windows or fabricated gap candles are used. Studies operate on observed bars; missing intervals and partial aggregation buckets remain limitations of the input, not assumed continuous data. Indicators do not change strategy results, entry eligibility or signal states. Parameters are fixed in this version. Selection is session state, not a saved layout.

Volume and VWAP are enabled only when the entire revealed input has non-null, finite, nonnegative volume classified as tick or exchange. Zero volume is valid; zero cumulative volume gives no VWAP. Missing volume invalidates the VWAP calculation from that candle through the London day. Earlier values are never revised using future missingness. A new London day starts a new accumulator. No volume is fabricated. Tick-weighted VWAP is a proxy, not exchange trade-volume VWAP. A London calendar day is not an exchange trading session. Weekly/monthly candle VWAP uses those candles' timestamps and weights, not reconstructed intraday VWAP.

The OHLC strip follows the crosshair; without a selected candle it shows the latest revealed bar. All timestamps use Europe/London. Oscillators and volume have independent panes and price scales. Drawing clicks are limited to the main price pane, and drawing SVG is clipped to that pane.

## Verification

Deterministic tests cover independent SMA/EMA values, classic Wilder RSI seed, ATR gap handling, population deviation, MACD warmups, summer/winter London midnight, zero/missing/unclassified volume, and prefix invariance for all studies during replay. No real dataset is bundled or claimed verified. Production builds check the supported Lightweight Charts 5.0.9 series/pane API types. Local preview/browser QA is unavailable in this managed environment; imported-data indicator rendering has not yet been browser-verified. Physical iPhone/Safari coverage remains pending.

Official API reference consulted: https://tradingview.github.io/lightweight-charts/docs/api/interfaces/IChartApiBase and the pinned package's bundled typings (5.0.9). No new charting library or feed is introduced.
