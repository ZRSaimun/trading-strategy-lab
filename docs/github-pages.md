# GitHub Pages browser workspace

The requested URL is https://zrsaimun.github.io/trading-strategy-lab/.

GitHub Pages serves static files, not the Python API, PostgreSQL, server sessions or a background alert worker. The Pages build therefore explicitly runs a **browser-local research mode**. It is functional for CSV charts, saved manual drawings, watchlist, local audit history, historical replay, basic pattern observations, research backtesting and demo research journal. It is not an authenticated deployment of the private Docker server.

## Enable hosting once

1. Open https://github.com/ZRSaimun/trading-strategy-lab/settings/pages.
2. Under Build and deployment, select Source: **GitHub Actions**.
3. Open Actions → Deploy browser research workspace to Pages → Run workflow → main.
4. Wait for both build and deploy jobs to succeed. Then open the URL above.

The GitHub connector used to prepare this change has no Pages configuration action. GitHub's default workflow token cannot automatically enable an unconfigured Pages site; do not create or paste a personal access token to bypass this setup step. Subsequent pushes to main redeploy automatically. Repository privacy and Pages availability depend on your GitHub plan; making a repository private alone does not make a Pages website private.

## Data and privacy

The public interface contains no bundled market data or credentials. Import only authorized, completed one-minute bars. Imported data, drawings, watchlist and the last 200 audit records are saved in IndexedDB on the current browser profile. These are not uploaded to the Python API or committed to Git. No password prompt is shown: a static JavaScript password prompt would not provide server authentication.

Browser storage is not encrypted by this app and is accessible to other scripts under the same origin. GitHub project sites share an origin. Use a dedicated browser profile and device lock for sensitive research; use the private Docker deployment for account-based access. Private browsing, clearing site data or changing browser/device may lose the local data. Reimport original CSVs to restore datasets and export drawing JSON for records. JSON restore and a full browser-backup facility are still pending. Concurrent edits across tabs are not transactionally version protected; edit in one tab.

Browser mode always labels imported prices historical and emits WAIT. It never creates executable quotes, trade orders or confirmed demo signals. Data sources are not connected remotely.

## Build locally

```sh
cd frontend
npm ci
npm test
NEXT_PUBLIC_DEPLOYMENT=pages NEXT_TELEMETRY_DISABLED=1 npm run build
```

This generates `frontend/out` with the `/trading-strategy-lab` base path. The regular build without NEXT_PUBLIC_DEPLOYMENT retains the authenticated server configuration and Docker backend proxy. Never put secrets into NEXT_PUBLIC environment variables.

## Replay and analysis

Replay reveals one aggregated candle at a time. Analyses receive only that prefix; manual drawings and their editor are hidden during replay because existing annotations could reveal future information. The imported dataset is still available in browser memory: this is a research replay, not a security boundary against inspecting your own file. The chart's latest close and timestamp follow the replay cursor.

Generic detector version `structure-research-v1` uses two strictly lower highs on each side to confirm swing highs, and two strictly higher lows on each side for swing lows. Confirmation waits for the second right-hand bar. A wick outside an unbroken confirmed swing and same-bar close back inside forms a sweep observation. A closing cross of an unbroken confirmed swing forms a structure-break observation. Three candles form an FVG only when the first and third wicks do not overlap. Observed-at timestamps use the last candle's **close boundary**, not its open timestamp. These are formation observations; FVG mitigation, displacement, contextual MSS/CHOCH, defended retests, spread and news policies are not implemented. No trading entry is inferred.

A first closing support break remains a structure observation with WAIT; it cannot produce a SELL signal. Five deterministic frontend tests verify parsing/aggregation, calendar buckets, sweeps, structure timing and replay isolation.
