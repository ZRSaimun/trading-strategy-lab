# Architecture

Next.js/React/TypeScript renders the terminal. Lightweight Charts supplies candlesticks, price lines, crosshair, pan and zoom. The UI projects persisted price/time coordinates onto an SVG overlay for notes, zones and trendlines. This is a basic overlay, not yet a supported series-primitive plugin implementation. Direct drag handles, rays, Fibonacci and undo/redo are not yet available. Coordinate editing is available in the inspector.

Same-origin `/api/*` requests are reverse-proxied by Next.js to FastAPI. The HttpOnly owner session cookie never contains the stored session record; the database stores only its SHA-256 digest with an eight-hour expiry. Password hashes use Argon2id. The API validates an authenticated session on every research endpoint.

PostgreSQL stores normalized candles, dataset manifests, drawings, watchlists, sessions and audit records. Alembic owns schema versions. Dataset SHA-256, source, retrieval time, volume type, actual coverage and gap counts are retained. Raw CSV archival is not yet implemented. Financial prices currently use floating point for chart research, not accounting or execution.

Only one-minute imports are supported. Aggregation uses UTC calendar boundaries: Monday for weeks and first calendar day for months. Session-specific exchange calendars and corporate actions are not implemented; aggregates expose observed-minute counts and quality warnings. Long gaps can be closures or missing data and are not classified. Chart output is capped at the last 2,000 aggregate bars; server supports `before`, but UI lazy loading remains pending.

No background worker, Redis, hosted service, live-data adapter or trading integration is enabled. Future strategy modules must be independent of chart rendering and consume completed, timestamped bars. AI annotation routes must use a separate scoped authorization model; an owner cookie is not an AI connector.

## Browser-only deployment

A conditional static export removes server rewrites and uses a separate IndexedDB adapter with no server authentication claims. The regular Docker/server build retains the authenticated API. A shared TypeScript research module provides prefix-only replay observations in both UI modes. See github-pages.md.

## Historical simulator

`frontend/lib/backtest.ts` is a deterministic research engine isolated from charts and transport. A forward-only candidate state machine feeds next-open execution. Configuration, raw candle snapshot, versions and modeled trades can be exported. The same UI computation works with Pages data or authenticated API chart data. Saved reports are client-supplied research records; server computation and verification are not claimed. See backtesting.md.
