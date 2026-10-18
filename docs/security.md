# Security and operations

## Current controls

- Loopback-only web exposure in Compose; no published database/API ports.
- No registration, hard-coded password, broker credentials, or provider keys.
- Argon2id owner password hashing; hashed, expiring and revocable sessions.
- HttpOnly SameSite=Strict cookies; secure flag configured for HTTPS.
- Cross-origin mutations rejected; input schemas reject unknown properties and non-finite drawing coordinates.
- Login throttling: five attempts per client address per 15 minutes, in-memory and single-process only.
- Drawing version checks and audit entries for saves/deletes; import and watchlist audit records.
- Next.js telemetry disabled in Docker. No application analytics trackers.

Not production security certification: TOTP/passkeys, distributed API rate limiting, tamper-resistant audit retention, CSP, streaming upload limits at a reverse proxy, cross-process login throttling and session cleanup are outstanding. Do not publish this foundation directly on the public Internet.

For private remote access, use a private VPN and HTTPS reverse proxy. Update PUBLIC_ORIGIN to the exact HTTPS origin and COOKIE_SECURE=true, restrict VPN membership, and verify access and origin behavior. Tailscale deployment has not been configured or tested. Do not bind to `0.0.0.0` on the host merely to obtain remote access.

## Back up

Stop importing/editing while taking a consistent backup. The following contains private data; encrypt it with your chosen backup system and store it outside Git:

```sh
mkdir -p backups
chmod 700 backups
docker compose exec -T db pg_dump -U lab -d lab -Fc > backups/lab.dump
chmod 600 backups/lab.dump
```

Back up `.env` separately using encrypted storage. Restoring uses the configured database password, so preserve it. Password hash backup is not plaintext password backup.

## Restore to an existing database (destructive)

The restore command replaces matching database objects. First preserve another backup. Stop API/web, then restore and restart:

```sh
docker compose stop web api
docker compose exec -T db pg_restore -U lab -d lab --clean --if-exists --no-owner < backups/lab.dump
# Prevent a historical backup from reviving login sessions or previously revoked AI tokens.
docker compose exec -T db psql -U lab -d lab -v ON_ERROR_STOP=1 -c "BEGIN; DELETE FROM records WHERE key LIKE 'session:%'; UPDATE records SET value=jsonb_set(value::jsonb, '{revoked}', 'true'::jsonb)::text WHERE key LIKE 'ai-token:%'; COMMIT;"
docker compose up -d api web
```

Only restart if restore and authentication invalidation succeeded. Log in again and issue fresh AI tokens; old sessions and AI tokens must not be accepted after recovery. Verify login, candle coverage, drawing coordinates and audit history after recovery. Backup/restore commands have not been exercised here because Docker is unavailable in the development environment. Schedule and test backups on the target installation.

## External display frame

Market Charts adds an explicitly labelled cross-origin TradingView widget. Its public symbol/theme/timeframe configuration contains no research data or keys. The provider frame cannot read host-origin browser storage. It makes third-party requests and can be disabled in that view; see market-display.md.

## Historical provider credential vault

Provider keys are locally Fernet-encrypted in ignored files, never browser configuration or query parameters. They are read only by the private backend and sent to one pinned HTTPS provider via Authorization. No credential upload route is exposed. Master-key permissions, separate encrypted backups and target-machine mount access require operator verification. This is not protection against a fully compromised host. See provider-setup.md.

## Scoped AI access

The private server supports hashed scoped AI tokens, expiry/revocation, versioned and idempotent audited drawing/notes/watchlist writes, and an official MCP SDK endpoint. See ai-access.md for supported tools, single-worker rate-limit assumptions and client verification limits. No OAuth or intended-ChatGPT connection is claimed.

An isolated Docker acceptance script is included (`python scripts/smoke_compose.py`). It generates disposable credentials, uses a randomly named Compose project, tests the web/API/MCP proxy, then removes only that project's containers and volumes. It requires port 3000 to be free. It also dumps the disposable fixture database and restores it into a separate database, checking candle/drawing/audit counts and invalidation of restored sessions/AI tokens. It does not replace the active database and is not an owner-data restore drill or target-host VPN verification.
