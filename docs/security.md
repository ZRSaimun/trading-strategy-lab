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

Not production security certification: TOTP/passkeys, scoped AI tokens, encrypted provider-secret storage, global API rate limiting, tamper-resistant audit retention, CSP, streaming upload limits at a reverse proxy, robust concurrent first-write conflicts and session cleanup are outstanding. Do not publish this foundation directly on the public Internet.

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
docker compose up -d api web
```

Verify login, candle coverage, drawing coordinates and audit history after recovery. Backup/restore commands have not been exercised here because Docker is unavailable in the development environment. Schedule and test backups on the target installation.
