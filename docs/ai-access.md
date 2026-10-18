# Private AI API and official MCP connector — v0.11

## What is implemented

The private FastAPI server provides owner-managed, random bearer tokens with four scopes: `charts:read`, `drawings:write`, `notes:write`, `watchlist:write`. Tokens expire in 1–720 hours, can be revoked immediately, and are returned only on creation. Only a SHA-256 token lookup hash is stored; raw tokens are excluded from listings and audit logs. Bearer credentials deliberately authorize actions within their scopes: issue read-only tokens unless writes are intended. Active issuance is capped at 50 tokens and retained idempotent writes at 10,000 per token.

The official MIT-licensed MCP Python SDK `mcp==2.3.0` provides a stateless JSON-response Streamable HTTP endpoint at **`/api/mcp`**. It supports the SDK's negotiated protocol revisions; protocol parsing is not hand-written. The parent FastAPI lifespan starts a fresh SDK transport/session manager at each startup. Transport host/origin allowlists are explicit and must agree with `PUBLIC_ORIGIN` in deployment. The endpoint requires a bearer token for discovery and every subsequent request. No browser CORS wildcard, unrestricted shell tool, arbitrary code execution, provider-key tool, broker endpoint or order tool is present.

The same tool service is available over authenticated JSON HTTP:

- `GET /api/ai/tools` — input JSON schemas and scope descriptions.
- `POST /api/ai/tools/{name}` — direct tool arguments as JSON.
- Owner-cookie-only `/api/ai/tokens` GET/POST, DELETE `/api/ai/tokens/{id}`, `/api/ai/status` and `/api/ai/notes`.

## Actual tools

| Scope | Tools |
|---|---|
| charts:read | list_instruments, get_instrument_metadata, get_candles, get_drawings, get_data_quality_status, get_signal_history, get_backtest_results, get_watchlist |
| drawings:write | create_chart_drawing, update_chart_drawing, delete_chart_drawing |
| notes:write | save_analysis_note |
| watchlist:write | update_watchlist |

Tool schemas reject unknown fields, non-finite prices, disabled/unknown instrument IDs and oversized requests. Candle reads are bounded to 2,000 aggregated candles, with source/coverage/freshness labels; imported history never becomes a live quote. Signal history contains saved historical replay observations only. Reports are saved simulations, not a new server-side backtest execution service.

MCP tools with parameters use a typed `request` object, e.g. `get_candles` arguments `{"request":{"instrument":"XAUUSD-IMPORT","timeframe":"5m","limit":100}}`. Parameter-free tools use `{}`. The direct JSON HTTP API omits the `request` wrapper.

Every write requires an idempotency key. Repeating identical arguments returns the original result; using that key for a different operation returns a conflict. Drawing update/delete require exact current versions. Creation requires version zero. AI provenance, creator and latest editor are retained; manual edits preserve AI-origin provenance. AI-origin levels/notes and saved drawing entries are visibly labelled, with blue geometric annotations. Notes and drawing changes produce AI-attributed audit records. Watchlist changes use a revision shared with owner edits.

The application uses existing versioned Record/Audit database storage; no additional table migration is required. PostgreSQL row locks and unique record keys serialize concurrent changes; a conflicting creation returns 409. SQLite remains single-process development only. Token expiry/revocation are checked in the database on each request and again within the tool transaction. A 120-requests/minute/token in-process transport throttle assumes one API worker. A multi-worker production service needs shared rate limiting. Retired token/idempotency record cleanup is not automatic.

## Private setup and verification

1. Run the documented Docker setup with an owner password. Set `PUBLIC_ORIGIN` to the exact host. Use HTTPS and `COOKIE_SECURE=true` for remote access; do not publish database/API ports.
2. Import authorized completed candles through Data Sources or configure an entitled private provider. There is no bundled real market dataset.
3. In **AI Chart Assistant**, issue a short-lived read-only token. The token is shown once, held in UI memory only, and is not included in browser workspace backups.
4. Configure a compatible MCP client with this private server URL and `Authorization: Bearer <token>` in that client's secure configuration. Never put the token in the URL, GitHub, a command argument, source code or chat.
5. Run the provided official-SDK verification client on a machine able to reach the server:

```sh
.venv/bin/python scripts/verify_ai_connection.py --url https://YOUR_PRIVATE_HOST/api/mcp
```

The client prompts for the token invisibly. It lists tools and reads quality status without printing candles or credentials. For an explicitly authorized temporary drawing test, add `--verify-drawing --time YOUR_UTC_EPOCH --price YOUR_PRICE` with drawings:write scope. It creates then deletes a clearly marked test note. Inspect the owner Audit Log. Revoke the token, then run the read test again to confirm denial.

## Verification evidence and limitations

Automated integration tests use the actual official SDK client through its HTTP transport and the application's ASGI stack: discover/list tools → read candles → create AI drawing → owner inspects drawing/audit → revoke → subsequent HTTP 401 and denied write, with no extra drawing. Further tests cover owner authentication, secret hashing/non-disclosure, scopes, expiry, rate limiting, idempotency conflicts, stale versions, manual edits preserving AI origin, strict schemas, missing/stale quality, exact identities, notes and shared watchlist revisions.

This is **not** an end-to-end connection from the user's intended ChatGPT client. Custom-header clients are supported; OAuth authorization-server discovery/consent is not implemented. ChatGPT clients that require OAuth cannot connect through a bearer-only configuration. Do not claim ChatGPT is connected merely because SDK tests pass. GitHub Pages has no Python server, token store or MCP endpoint; its AI page explains NOT CONNECTED. The actual private host, HTTPS/VPN deployment, live feed, intended-client verification, server detection snapshots, demo-candidate write tools and backtest job execution remain incomplete.

## Primary sources researched

- Official SDK ASGI/lifespan and host protection: https://py.sdk.modelcontextprotocol.io/run/asgi/
- Official SDK source and MIT license: https://github.com/modelcontextprotocol/python-sdk
- Exact pinned package: https://pypi.org/project/mcp/2.3.0/
- Protocol revisions/transports: https://modelcontextprotocol.io/specification/

No paid service, cloud host, subscription or brokerage account was activated.

### Canonical proxy route

Use the web server's canonical `/api/mcp` URL without a trailing slash. Its explicit Next.js rewrite forwards directly to the internal SDK `/api/mcp/` route, preserving authentication without a redirect. Clients deliberately do not follow MCP redirects, so a trailing-slash redirect to an internal container hostname is a deployment error, not a reason to relax client redirect security. The Compose smoke test exercises this exact path. MCP database operations run in worker threads so candle reads do not block the ASGI event loop. Strict AI models reject implicit number-string coercion and out-of-range timestamps.

### Full stack evidence

GitHub Actions passed the complete Docker smoke workflow on commit 7bdceb5 after the proxy fix. It built PostgreSQL/FastAPI/Next.js, authenticated through the web service, imported labelled deterministic software candles, created and audited an AI note drawing, connected the official MCP SDK through the actual proxy, then denied the revoked token. The recovery extension additionally restores a fixture dump into a separate disposable database and checks retained candle, drawing and audit records. This is real container/runtime integration evidence, not a live feed or intended-ChatGPT-client test. See the checks workflow for each subsequent revision's result.

After a database restore, invalidate all owner sessions and revoke every restored AI token before reopening the application. Otherwise a snapshot taken before revocation could reintroduce valid historical credentials. The security guide includes the transactional PostgreSQL command, and the Docker recovery check simulates this case on a disposable restored database.
