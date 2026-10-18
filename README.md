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

**Imports replace the instrument's dataset atomically**, do not append. Back up before replacing a dataset. The current limit is 12 MB / 100,000 one-minute rows per import; ten-year ingestion is a future pipeline task. The source identifier must distinguish the exact venue/proxy. Never import NQ futures or broker CFDs under the NDX cash-index identity.

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

## Research backtesting

Open Backtesting to compare five versioned research approximations with costs, next-open eligibility, conservative OHLC fills, chronological sample splits and reproducible JSON exports. Add selected simulations to Trading Journal. See [rules, cost model and limits](docs/backtesting.md). These are not verified profitable strategies or broker fills.

## Conditional replay alerts

Save rules in Research Alerts, select matching instrument/timeframe in Charts and advance replay. Level acceptance, sweeps and FVG observations create deduplicated historical event records. See [rules and limitations](docs/alerts.md). No live or background alert delivery is connected.

## White day mode and market charts

The app now opens in white day mode with a mobile-visible theme switch and saved preference. Market Charts requests provider-hosted display charts for the watchlist; Research Charts retains the imported-data engine. See [exact feed choices, licensing, privacy and verification limits](docs/market-display.md). The display integration does not supply raw data to our simulator.

## Private historical API adapter

Data Connection documents and reports the disabled-by-default Twelve Data adapter. On a private server with an owner-provided encrypted key and verified entitlement, it can import a bounded window of completed Gold candles into our engine. No provider account is activated. See [setup, research, costs and remaining verification](docs/provider-setup.md).

## Market availability and bug fixes

Some exact index/futures feeds are blocked by the display provider. The app identifies confirmed restrictions and offers explicitly labelled alternative instruments without silently replacing the original. Mobile market selection and concurrent browser persistence have been repaired. See [investigation and evidence](docs/bugfix-2026-10-17.md).

## Research chart indicators

Open Research Charts → Indicators to choose price overlays and separate oscillator/volume panes. Crosshair movement shows candle OHLC. Studies use only the candles revealed by replay. Volume and VWAP require valid classified volume; they never invent volume. See [formulas, warmups and limitations](docs/indicators.md).
