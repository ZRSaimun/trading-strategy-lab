# Private raw-data adapter and deployment (v0.6)

## What changed

A Twelve Data historical adapter is implemented behind the authenticated Python service. It is disabled by default and has not been activated with a real account. The public GitHub Pages Data Connection page reports NOT CONNECTED and cannot hold a secret or call this private provider route.

The only mapped series is `XAUUSD-TD` → exact provider symbol `XAU/USD`, one-minute UTC bars. It is independent of `XAUUSD-IMPORT`, the TradingView OANDA display and all Nasdaq identities. Nasdaq mapping/entitlement is unverified and not enabled. The provider response must agree on symbol, interval and UTC timezone or the import fails closed.

Completed bars are validated, sorted and checked for duplicates, OHLC errors and future/incomplete timestamps. Source candle timestamps must use the canonical ASCII `YYYY-MM-DD HH:MM:SS` UTC spelling; Python's otherwise lenient non-padded or Unicode-digit timestamp parsing is not accepted, so ambiguous vendor source text cannot be silently normalized before snapshot hashing. The request is bounded to 1–5,000 candles ending at the selected UTC boundary. This is a replacement of the provider-specific dataset, not append/pagination or a live stream. Existing CSV datasets remain separate. Successful imports become available in private Research Charts, Backtesting and historical Research Alerts.

The bounded HTTP JSON decoder also quarantines excessively nested responses that exceed the parser's recursion depth, returning a sanitized provider error instead of propagating an unhandled server exception. This is a transport robustness check only; it does not authenticate provider prices, prove source rights or activate a feed.

The adapter now rejects non-integer request counts (including Python booleans) and nonfinite, malformed or out-of-range UTC request/observation boundaries **before any provider HTTP call**. Direct `normalize()` callers also reject nonfinite, nonnumeric, negative, pre-completion and out-of-range observation clocks before processing any candle. Without this gate, `NaN` or positive infinity could silently bypass the completed-candle cutoff. This is caller-input validation only; it does not independently authenticate the clock. Valid fractional epoch boundaries retain the existing second-precision request format; this is input validation, not an independently trusted clock.

The low-level Twelve Data client also rejects negative historical end times and requests whose end time is later than the last fully completed minute relative to the caller's supplied observation clock. This applies even when a direct offline/prospective caller bypasses the HTTP import route. It does not independently attest that the caller's clock is correct, that the vendor actually served the requested interval, or that a paid call is authorized. The exact completed boundary is allowed; fractional seconds remain supported.

The API uses a pinned HTTPS host/path, the official Authorization header, no redirects and a streamed response-size limit. A successful HTTP 200 response with any `Content-Range` header is rejected as an ambiguous partial-entity claim, even when the JSON is syntactically valid; HTTP 206 remains unsupported. Successful JSON bodies must decode as strict UTF-8; UTF-16/UTF-32 and a UTF-8 byte-order mark are rejected even if Python's default bytes JSON parser would accept them. Invalid encodings return a sanitized provider error, never a partially accepted candle. An explicitly declared successful-response `Content-Type` must be JSON (`application/json`, optionally with a UTF-8 charset); duplicated, contradictory or non-JSON media-type claims are rejected before parsing. An absent header is tolerated for compatibility and is **not** evidence of source authentication. When the HTTP response declares `Content-Length`, the bounded identity-encoded entity body must match that length exactly; a simultaneous `Transfer-Encoding` and `Content-Length` is rejected as ambiguous framing. Responses without a declared length remain bounded by the 3 MB cap. An optional `Transfer-Encoding` must be exactly one `chunked` coding (case-insensitive); duplicated, compressed or chained transfer codings fail closed. The HTTP client removes chunk framing before the bounded entity-body digest. This does not authenticate the provider or prove TLS/network integrity. These checks protect receipt completeness, not provider authenticity or data rights. Credentials never appear in URLs, response payloads, normal audit records or browser configuration. There is one request per minute and one in-flight import per API process. Use a single API worker; cross-process scheduling/rate limits are not implemented. No automatic requests are scheduled.

## Research findings and purchasing gate

Reviewed 2026-10-17 using official documentation:

| Option | Verified finding | Still needs verification |
|---|---|---|
| Twelve Data | Basic is advertised free with 800 daily API credits; Grow is advertised from USD 29/month and commodities are listed in that product family. Prices vary with credit allocation/billing. Historical requests support at most 5,000 output records. | Exact XAU/USD entitlement, quote latency, retention, internal display and non-display analysis rights; account-specific cost and exact history depth. Do not assume the cheapest tier authorizes the entire project. |
| Massive | Separate indices, currencies and futures product/pricing pages exist. | Exact Gold/NDX symbols, package pricing, exchange terms, historical depth and intended-use permissions; no adapter or account is connected. |
| MT5 Python | `copy_rates_range` retrieves terminal-available bars; coverage depends on broker history and Max bars in chart; use UTC. | Broker permission, terminal compatibility and actual instrument history. No broker account or terminal was connected. |
| GitHub Pages | Static hosting cannot run this Python service/database or keep an API secret. | An owner-controlled private machine or server is required. |
| Tailscale Serve | Can reverse-proxy the local web port within the tailnet using HTTPS. | Owner's device/account, access policy, DNS/certificates and operational verification. No VPN access was created. |

Sources:
- https://twelvedata.com/pricing
- https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage
- https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices
- https://twelvedata.com/docs/ai/ai-data-assistant (official Authorization header guidance)
- https://massive.com/pricing?product=indices
- https://massive.com/pricing?product=currencies
- https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://tailscale.com/docs/reference/tailscale-cli/serve
- https://tailscale.com/docs/how-to/set-up-https-certificates

No subscription has been purchased. Ten-year minute coverage is not promised. Provider documentation says minute history is limited and varies by symbol/interval; check actual earliest coverage before designing a backtest. A data API subscription is not automatically a redistribution license or permission to expose research publicly.

## Local private setup

Use an owner-controlled computer with Docker. Do not do this on GitHub Pages or paste your key into chat.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
python scripts/configure.py
```

If `.env` already exists, keep it; configure.py intentionally refuses to overwrite it. Confirm the provider account and intended-use rights before locally saving any key. The following reads a key through hidden terminal input and writes an encrypted credential file:

```sh
python scripts/provider-key.py
```

It creates ignored `.secrets/provider-master.key` and `.secrets/twelvedata.enc`, with owner-only file permissions. Keep the master key private and back it up separately in encrypted storage. Encryption does not protect against a fully compromised host that can read both files. For Docker on Linux, the API user must have permission to read these owner-only files (the image's `lab` user normally has UID/GID 1000); verify UID ownership/mount access rather than making secrets world-readable. The runtime mount is read-only. Docker Desktop file-permission behavior differs; validate on the actual target.

The adapter remains disabled. The current owner policy is free-only; these instructions are for a later separately approved change. After account rights and costs are approved, explicitly set `FREE_ONLY=false` and `TWELVEDATA_ENABLED=true` in local `.env`, then start:

```sh
docker compose -f compose.yaml -f compose.provider.yaml up --build -d
```

Open http://localhost:3000, log in and choose Data Connection. Confirm it reports an encrypted credential and enabled status. Choose the historical end time/count, confirm rights and dataset replacement, then import. No key is entered into a browser. Response failures are sanitized and leave the existing dataset unchanged. Quota/permission errors are not bypassed. A failed provider attempt still consumes the local rate-limit interval to avoid credit-spamming.

For plain local development, set `PROVIDER_MASTER_KEY_FILE`, `TWELVEDATA_KEY_FILE`, `TWELVEDATA_ENABLED` and `MARKET_ARCHIVE_DIR` as server-side environment variables, then run the backend as documented in README. These variables must never use a NEXT_PUBLIC prefix. The master/key variables are filesystem paths, not plaintext credentials.

## Private remote access

Keep Compose bound to 127.0.0.1:3000. Once the owner configures Tailscale and restricts tailnet access, its documented Serve command can proxy the local service:

```sh
tailscale serve --bg http://127.0.0.1:3000
tailscale serve status
```

Set PUBLIC_ORIGIN to the exact resulting HTTPS origin and COOKIE_SECURE=true in `.env`, then recreate API/web services. Test login, cross-origin rejection, private-only access and logout from the intended devices. Use Serve for tailnet access, not public Funnel. Tailscale HTTPS certificate names enter public certificate-transparency logs; choose non-sensitive host names. No Serve command was run here and remote access has not been verified.

## Storage and backup

Normalized bars and manifests are in PostgreSQL. A vetted source-field snapshot is stored under MARKET_ARCHIVE_DIR with a SHA-256 filename. This snapshot retains only symbol/interval/timezone and accepted completed OHLC values; it is not the provider's entire raw HTTP response. Its hash_scope is explicit. Unknown response fields are not archived. Archive write happens before DB commit; a later database failure can leave an unused archive file, but cannot half-replace a dataset.

Compose persists archives in the `market-archive` volume. Include this volume in encrypted backups alongside the database and separately protected secrets; a database dump alone does not contain source archive files. Never commit either licensed data or secrets. Existing backup/restore documentation still applies, but a target-machine restore drill remains outstanding.

## Verification and remaining gaps

Eight new tests cover credential encryption/denial, exact metadata, complete-candle normalization, header-only credentials, pinned host, HTTP errors/quota, redirect rejection, count boundaries, auth/disable gates, manifest/archive/chart persistence, audit secrecy, request throttle and wrong-symbol/rights rejection. They use controlled HTTP responses, not real market data. Total suite: 16 backend + 24 frontend tests.

Unverified: live provider account/entitlements, actual Gold feed/history coverage, Nasdaq mapping, Docker execution and secret-mount permissions, real credential import, browser interactions, VPN deployment and restore procedures. No current market price, live integration, ten-year history, profit or external AI connection is claimed.

Backtest UI excludes incomplete aggregate candles at the bounded window edges and records the exclusion count, rather than treating partial 5m/1H candles as complete. It does not fill gaps; the simulator retains conservative gap handling.

## Pricing recheck — 2026-10-19 (Europe/London)

The currently rendered individual pricing page shows Basic at USD 0, a selected Grow monthly configuration at USD 79 (377 API + 8 trial WS), Pro at USD 229, and Ultra at USD 999. These are the page's selected configurations, not a confirmed minimum quote or approved project budget. Grow lists commodities and internal display access; Ultra explicitly lists internal non-display access. Exact XAU/USD/NDX entitlement, historical depth and permission for backtesting/AI processing must therefore be confirmed with the provider; a display subscription is insufficient evidence of analysis rights. No plan was purchased or activated. Source: https://twelvedata.com/pricing

Hosting also remains unselected. GitHub Pages is static hosting, not the Python/PostgreSQL service. Render's official free-tier documentation states web services sleep after inactivity and free Postgres expires after 30 days; this is not an approved permanent hosting design. No paid hosting price has been approved and no account was created. Sources: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages and https://render.com/docs/free.


## Licensing recheck — 27 October 2026 (no account entitlement)

Twelve Data's [current personal/commercial-use guidance](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage) distinguishes individual plans intended for personal, internal and non-commercial use from business plans with commercial internal/display rights subject to exchange agreements. Individual plans do **not** grant raw-data redistribution or commercial third-party display. Its [current individual pricing](https://twelvedata.com/pricing) distinguishes Grow's internal display from Ultra's advertised internal non-display data access; the [attribution guidance](https://support.twelvedata.com/en/articles/12647398-attribution-guidelines-for-using-twelve-data) addresses externally published derived data. None of these public descriptions confirms this account's XAU/USD instrument entitlement, retained historical rights, AI analysis, paper execution use, or Gold-specific quote side. Obtain explicit provider confirmation of the exact symbol, price side, venues, commercial/personal usage, backtesting/AI processing, retention and display scope **before any activation or paid call**. Do not treat the provider's public instrument catalog as proof of account access.
