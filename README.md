# Trading Strategy Lab

Private, local-first historical trading research. **Phase 1 foundation; not a complete trading platform.** No live feeds, AI connector, confirmed signals or orders are enabled. Basic completed-bar research observations and replay are available. No historical market data or credentials are distributed.

## GitHub Pages

The browser-local workspace is built for https://zrsaimun.github.io/trading-strategy-lab/. See [one-time Pages setup and mode limitations](docs/github-pages.md). It stores imported data on your device and is separate from the authenticated Docker server.

## Start locally

Install Docker with Compose, Python 3.10+ and the small configuration dependency:

```sh
python -m venv .venv
. .venv/bin/activate
pip install argon2-cffi==23.1.0
python scripts/configure.py
docker compose up --build -d
```

Open http://localhost:3000 and unlock with the password you created. The web port binds **only to loopback**. PostgreSQL and FastAPI have no host port bindings. Never commit `.env`. There is no registration or default password.

1. Open Data Sources. Select the exact instrument and identify your authorized source.
2. Import a one-minute CSV with headers `time,open,high,low,close` and optional `volume`. Time must contain an explicit UTC offset, for example `2024-01-02T10:00:00Z`.
3. Select a timeframe. Only observed bars are aggregated; missing minutes are never fabricated.
4. Choose Level, Zone, Trendline or Note and click chart coordinates. Zones and trendlines require two clicks. Drawings save immediately.
5. Select a saved drawing to edit its exact epoch-time/price coordinates or label, or delete it. Refresh to verify persistence. Export JSON is available.

**Legacy CSV imports replace the instrument's dataset atomically**, do not append. Back up before replacing one. The existing browser CSV route remains size-limited. An **experimental separate append-only ZIP archive importer** with source-isolated datasets and a read-only Historical Archives view is documented in [HistData import instructions](docs/resumable-histdata-import.md). It requires a reviewed private database schema and is not a cloud ZIP upload or automated ten-year deployment. The source identifier must distinguish the exact venue/proxy. Never import NQ futures or broker CFDs under the NDX cash-index identity.

## Development without Docker

```sh
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
# Supply OWNER_PASSWORD_HASH through your environment. Do not paste a password into commands.
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
NEXT_TELEMETRY_DISABLED=1 npm run dev
```

Without `DATABASE_URL`, the API uses a local SQLite database. Compose uses PostgreSQL. SQLite is for local single-process development. API documentation: http://127.0.0.1:8000/docs when running the backend locally. Docker keeps this port private.

## Checks

```sh
cd backend
PYTHONPATH=. python -m pytest -q
cd ../frontend
npm ci
NEXT_TELEMETRY_DISABLED=1 npm run build
npm test
```

See [architecture](docs/architecture.md), [status and acceptance](docs/status.md), [data licensing](docs/data-sources.md), and [security and recovery](docs/security.md).

## Read-only historical archive backtesting

The authenticated Backtesting screen can now select one ready source-isolated historical ZIP archive and fetch up to 20,000 aggregate candles via the existing paginated history API, with dataset hash checks and explicit window/cost limitations. No archive is uploaded or merged automatically, and BID-only history is not broker-executable data. See [archive-backed backtesting](docs/archive-backtesting.md).

## Experimental 4H CRT / ICT confirmation research

Authenticated **CRT / ICT Research** now screens source-isolated 4H sweep/reclaim candles, a configurable 40% manipulation-wick hypothesis, and causal next-block 15m structure/displacement with a previous-20-bar median. It reports absent verified volume, formal order-block evidence, and event calendars as **insufficient data**, never as permission to trade. Results are observational, not a profitability backtest. See [complete methodology](docs/crt-quant-research.md).

## Source-isolated NY close momentum research

The authenticated **NY Close Research** screen adds a read-only, historical US equity-session hypothesis using completed M1 BID-only candles from exactly one imported archive, a 20-prior-complete-session volatility gate, and 0×/1×/2×/3× illustrative friction comparisons. It uses America/New_York clock rules and deliberately refuses incomplete regular sessions. This is not a live or verified CFD edge; ETF academic results cannot be assumed to hold for Nasdaq CFD, Gold or WTI proxies. See [full research protocol and limitations](docs/ny-close-cfd-research.md).

## Research backtesting

Open Backtesting to compare five versioned research approximations with costs, next-open eligibility, conservative OHLC fills, chronological sample splits and reproducible JSON exports. Add selected simulations to Trading Journal. See [rules, cost model and limits](docs/backtesting.md). These are not verified profitable strategies or broker fills.

## Saved-strategy robustness review

**Strategy Robustness** compares each saved historical simulation's development, validation and holdout results, with caution flags for sample size, negative holdout returns, drawdown, missing provenance and incomplete windows. It never certifies a profitable strategy or trades on an owner's behalf. See [strategy robustness review](docs/strategy-robustness-review.md).

## Conditional replay alerts

Save rules in Research Alerts, select matching instrument/timeframe in Charts and advance replay. Level acceptance, sweeps and FVG observations create deduplicated historical event records. See [rules and limitations](docs/alerts.md). No live or background alert delivery is connected.

## White day mode and market charts

The Historical Archives viewer now includes a loaded-window data-quality panel for observed minutes, intraday partial buckets, unobserved spans and volume limitations. It does not confuse exchange closures with verified missing data. See [historical archive quality diagnostics](docs/archive-quality.md).

The app now opens in white day mode with a mobile-visible theme switch and saved preference. Market Charts requests provider-hosted display charts for the watchlist; Research Charts retains the imported-data engine. See [exact feed choices, licensing, privacy and verification limits](docs/market-display.md). The display integration does not supply raw data to our simulator.

## Private historical API adapter

Data Connection documents and reports the disabled-by-default Twelve Data adapter. On a private server with an owner-provided encrypted key and verified entitlement, it can import a bounded window of completed Gold candles into our engine. No provider account is activated. See [setup, research, costs and remaining verification](docs/provider-setup.md).

## Market availability and bug fixes

Some exact index/futures feeds are blocked by the display provider. The app identifies confirmed restrictions and offers explicitly labelled alternative instruments without silently replacing the original. Mobile market selection and concurrent browser persistence have been repaired. See [investigation and evidence](docs/bugfix-2026-10-17.md).

## Research chart indicators

Open Research Charts → Indicators to choose price overlays and separate oscillator/volume panes. Crosshair movement shows candle OHLC. Studies use only the candles revealed by replay. Volume and VWAP require valid classified volume; they never invent volume. See [formulas, warmups and limitations](docs/indicators.md).

## Browser workspace recovery

On GitHub Pages, open **Backup & Restore** to download a complete local workspace JSON file and restore it later. The file includes imported candles, drawings and retained research records. Restore replaces the current workspace after validation; save a backup and close other app tabs first. Backups are unencrypted and should be stored privately. See [recovery guide and limitations](docs/workspace-backup.md). Private-server database recovery remains separate.

## What remains

See [next priorities and current practical benefit](docs/next-priorities.md). The public app is not yet the complete privately hosted live-data/AI terminal. External charts, imported research, replay alerts and a verified AI connection are distinct capabilities; only the implemented ones are labelled working.

## Private AI chart access

The private server now includes owner-managed scoped tokens, an official MCP SDK HTTP connector and audited AI drawings/notes/watchlist updates. Use **AI Chart Assistant** to manage tokens on the private deployment. The public Pages page correctly reports NOT CONNECTED. See [supported tools, connection test and remaining ChatGPT/hosting requirements](docs/ai-access.md). Run the [isolated full-stack smoke test](scripts/smoke_compose.py) on a machine with Docker; CI also runs it.

## Free-only operation

The project now defaults to `FREE_ONLY=true`, blocking the external historical-data adapter before credential loading or network access. See [the free-only plan, enforced scope and unfinished cloud requirements](docs/free-only.md). No cloud account or paid subscription is activated by this configuration.

## Single-service free hosting preparation

A combined Next.js/FastAPI Docker image, explicitly free Render Blueprint and private Postgres schema are available. See [setup, enforced limits and cloud activation checks](docs/free-cloud-deployment.md). This prepares deployment; it does not create or activate cloud resources.
