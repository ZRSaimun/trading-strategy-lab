# Data and dependency licensing

Reviewed 2026-10-17. This build integrates no paid provider and includes no real market dataset.

TradingView Lightweight Charts 5.0.9 is Apache-2.0 licensed. Retain its LICENSE and NOTICE from the installed package in distributions; the chart's attribution logo remains enabled and the UI includes a TradingView link. Official references:
- https://github.com/tradingview/lightweight-charts/blob/master/LICENSE
- https://github.com/tradingview/lightweight-charts/blob/master/NOTICE
- https://tradingview.github.io/lightweight-charts/docs

The current SVG overlay is explicitly documented as an interim drawing implementation. Migration to the supported series primitive APIs is outstanding.

CSV import is an adapter for user-supplied authorized one-minute files. Authorization confirmation does not replace a provider license. You must verify private storage, retention, derived-data use and automated analysis permissions for your source. Test fixtures are fabricated deterministic **software test data**, never presented as real Gold history.

Massive, Dukascopy files and official MetaTrader 5 terminal history are investigation targets only. No prices, subscription coverage, ten-year guarantees or live entitlements have been verified or purchased. MT5 terminal history requires a compatible local terminal and depends on broker and terminal coverage. Any future integration needs a provider-specific licensing/pricing review and explicit approval before paid activation.

Symbol registry currently exposes XAUUSD user-declared OTC source and NDX user-declared cash-index source as separate imports. NQ is disabled; expiry, contract size, roll rules and sessions must be implemented before enabling futures. No automatic substitutions or continuous-contract stitching occur.

## Display-only provider charts

Version 0.5 adds an official TradingView embedded chart view. It is separate from Lightweight Charts and the CSV adapter, and is not an ingestion license or source for automated backtests. No raw dataset has been obtained. See market-display.md for coverage/attribution/privacy constraints and original sources.

## Disabled private historical adapter

The server includes a bounded Twelve Data XAU/USD one-minute adapter, activated only by owner configuration and explicit per-import rights confirmation. No real account or provider request was made during development. Nasdaq is not mapped. See provider-setup.md for official research sources, pricing caveats, retention rights and setup.
