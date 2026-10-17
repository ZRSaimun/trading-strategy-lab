# Private raw-data adapter and deployment (v0.6)

## What changed

A Twelve Data historical adapter is implemented behind the authenticated Python service. It is disabled by default and has not been activated with a real account. The public GitHub Pages Data Connection page reports NOT CONNECTED and cannot hold a secret or call this private provider route.

The only mapped series is `XAUUSD-TD` → exact provider symbol `XAU/USD`, one-minute UTC bars. It is independent of `XAUUSD-IMPORT`, the TradingView OANDA display and all Nasdaq identities. Nasdaq mapping/entitlement is unverified and not enabled. The provider response must agree on symbol, interval and UTC timezone or the import fails closed.

Completed bars are validated, sorted and checked for duplicates, OHLC errors and future/incomplete timestamps. The request is bounded to 1–5,000 candles ending at the selected UTC boundary. This is a replacement of the provider-specific dataset, not append/pagination or a live stream. Existing CSV datasets remain separate. Successful imports become available in private Research Charts, Backtesting and historical Research Alerts.

The API uses a pinned HTTPS host/path, the official Authorization header, no redirects and a streamed response-size limit. Credentials never appear in URLs, response payloads, normal audit records or browser configuration. There is one request per minute and one in-flight import per API process. Use a single API worker; cross-process scheduling/rate limits are not implemented. No automatic requests are scheduled.

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

The adapter remains disabled. After account rights and costs are approved, explicitly set `TWELVEDATA_ENABLED=true` in local `.env`, then start:

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
