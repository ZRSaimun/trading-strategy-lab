# Single-service free cloud deployment

This adds a combined Next.js/FastAPI image and a Render Blueprint with `plan: free`. It does not create accounts, projects, billing methods or subscriptions. The existing GitHub Pages site remains a browser-local workspace; it is not automatically connected to a private deployment.

## Runtime

`deploy/free.Dockerfile` builds Next.js standalone and installs the pinned Python backend. A non-root supervisor migrates the database, waits for API health, then starts Next.js on `$PORT` (default 10000). FastAPI binds only to loopback port 8000. Next.js proxies `/api/*`, including the canonical `/api/mcp` connector endpoint. If either server exits, the supervisor stops its peer. SIGTERM stops both.

The free profile requires HTTPS, a strong Argon2id password hash, persistent Postgres, `DATABASE_SCHEMA=tsl_private` and `FREE_ONLY=true`. SQLite is rejected. Remote databases require `sslmode=verify-full` and a root certificate supplied as `DATABASE_CA_PEM`; plaintext database URLs are never printed by startup validation. Migrations must succeed before serving traffic.

The API uses at most two database connections, transaction-local schema selection, a 30-second query timeout and one worker. CSV imports are capped at 2 MB and 5,000 candles per instrument, replacing the selected series atomically. This is a small research window, not ten years of minute data. Password verification is serialized to bound Argon2 memory. Node's heap is capped at 128 MB; this is not the process's total memory. Cloud limits can still suspend or terminate an instance.

## Database ownership and isolation

1. Choose the organization that owns the new free database. Its administrators will be able to manage it. The existing connected organization is `tripbhai Org`; a separate personal organization is also possible. No choice has been inferred.
2. Create a new **Free** Postgres project only after confirming the quoted charge is zero. Do not upgrade an organization, attach a payment method or buy an IPv4 add-on.
3. In Supabase, disable the Data API for this dedicated project: this app uses server-side SQL, not Supabase browser clients. Never add `tsl_private` to exposed schemas.
4. Copy the actual direct or **session pooler** connection from the project's Connect dialog. Use the IPv4-compatible session pooler when direct IPv6 is unavailable. Do not construct its hostname from a guessed region. Transaction pooling on port 6543 is rejected by the free profile.
5. Download the matching server root certificate from database SSL settings. Enable database SSL enforcement. Set `sslmode=verify-full` in the connection URL; certificate identity verification must succeed on the deployed host.

Alembic creates application tables and its version table in `tsl_private`, with no fallback to `public`. Startup revokes schema/table/sequence privileges from PUBLIC, `anon` and `authenticated` when those roles exist, and enables RLS with no browser policies. The server connects as the table owner. This is a single-owner deployment, not tenant isolation; database/account administrators remain privileged. Do not reuse a project containing unrelated application tables. Existing default-schema deployments are not silently moved: back up and migrate them intentionally.

## Render setup

Connect the existing GitHub repository in Render and create its Blueprint from `render.yaml`. Confirm the single web service is **Free** and no disk, managed Render database, cron or worker is added. Leave billing disabled; a free instance does not prevent overage billing on an account with a payment method. Set the account's available spend limits and review current quotas.

Fill secret environment values through Render's settings, never GitHub source or chat:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Actual Postgres direct/session URL, URL-encoded password, `?sslmode=verify-full` |
| `DATABASE_CA_PEM` | Full matching public root certificate, including PEM header/footer |
| `OWNER_PASSWORD_HASH` | Strong Argon2id hash generated with `scripts/configure.py` on a trusted computer; keep the password private |

Render supplies `RENDER_EXTERNAL_URL`; the supervisor uses it for the exact public origin and forces secure cookies. For a custom domain set `PUBLIC_ORIGIN=https://your-domain` explicitly. No plaintext password is bundled. Blueprint secret prompts occur only on initial creation; later secret changes must be entered manually.

The schema initialization requires create-schema/table permissions and ownership for RLS hardening. Migration failure stops startup rather than falling back to temporary storage. Check URL, pool mode, certificate, ownership and database availability in the host settings. Do not paste credentials into issues or logs.

## Verification and recovery

CI runs the existing separate-container acceptance test and `python scripts/smoke_compose.py --combined`. The combined fixture enforces a 512 MB container memory limit and checks owner authentication, Secure cookie attributes, 5,000-candle import/pagination, schema isolation/RLS, AI drawing and audit, official MCP transport, token revocation, restart persistence and dump/restore. All test candles are labelled software fixtures, not real market history. CI uses local Postgres, not an actual Supabase project, and HTTP loopback with a test-only cookie policy; it does not verify Render's TLS termination, Supabase pooler/TLS or iPhone rendering. It does not emulate Render's CPU quota.

Before calling cloud activation complete, check the actual HTTPS URL from the owner's iPhone, confirm unauthenticated data access returns 401, log in, import permitted historical data, save a drawing, restart the service and verify persistence. Then run `scripts/verify_ai_connection.py` with a separately scoped expiring token and revoke it after the test. Intended AI-client compatibility still needs its own test.

For private backups use an encrypted destination and `pg_dump --schema=tsl_private` with a compatible Postgres client, taking credentials from a trusted environment or secret manager. Never commit a backup. Test restores in a separate disposable database. Before reopening a restored deployment, delete restored `tsl_private.records` sessions and revoke every restored AI token using the procedure in `docs/security.md`, with schema-qualified table names. A Supabase database contains platform schemas; do not restore a whole-platform dump into another managed project.

## Limits

Render sleeps after 15 idle minutes, may restart and has no free persistent disk. No keep-alive workaround or reliable 24/7 alert promise is provided. The application data persists in Postgres, not the web filesystem. Supabase Free has a 500 MB database limit and inactivity pausing; monitor its dashboard. Free plans are suitable for evaluating this small private research workspace, not a guaranteed always-on terminal. Hosted authentication is private, but the service is reachable over public HTTPS; VPN-only networking is a separate unfinished deployment option.

Official references checked 2026-10-19: [Render free limits](https://render.com/docs/free), [Blueprint reference](https://render.com/docs/blueprint-spec), [Supabase connections and SSL](https://supabase.com/docs/guides/database/connecting-to-postgres), [Data API security](https://supabase.com/docs/guides/api/securing-your-api), [Supabase Free quotas](https://supabase.com/pricing). Current database changelog items concerning ltree/pgcrypto/btree_gist/custom operators do not affect this extension-free schema.
