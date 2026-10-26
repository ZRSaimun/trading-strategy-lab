# Loop 4 — manual-only Render release policy (static safeguard)

The repository Blueprint now declares autoDeployTrigger: 'off' (quoted for YAML
1.1 compatibility). This is a valid value documented by Render:
https://render.com/docs/blueprint-spec

**This is a source-code declaration, not proof of the live service settings.**
Render Blueprint auto-sync can itself apply changes and redeploy affected
services. Never assume a GitHub merge is safe until the exact service and
linked Blueprint are inspected.

Run from repository root:

    python scripts/check_render_release_policy.py

The standard-library script refuses non-manual deploy triggers, unexpected
resource types, paid plans, absent /api/health, enabled paid data feeds,
missing secret placeholders, extra environment keys and duplicate keys.
Diagnostics contain only policy labels, never credential values.
The backend test suite includes 19 synthetic positive/negative cases.

The script is a narrow text-policy checker, **not** a YAML parser, Render
schema validator, live-state attestation, backup drill or deployment
permission. Independently run Render Blueprint validation before syncing.

## Production release gate — not yet satisfied

1. Owner must identify the exact Render workspace, service ID and linked
   Blueprint. Independently verify actual service auto-deploy Off and
   Blueprint Auto Sync No. Do not infer the intended workspace from a list.
2. Record the current deployed Git SHA, /api/health result and database
   schema. Obtain an encrypted database backup and demonstrate restore to
   a disposable isolated database. Invalidate restored sessions and tokens.
3. Require full green CI on the exact candidate commit: backend, frontend,
   PostgreSQL concurrency/rollback acceptance and Docker smoke. Record
   skipped checks explicitly; review overlapping PRs and migrations.
4. Deploy the reviewed SHA manually only after backup/rollback verification.
   Do not create paid resources or add a payment method.
5. Verify /api/health, owner login, unauthenticated 401, private schema,
   read-only research workflows and the live SHA. On failure, roll back
   to the recorded prior deploy and reverify health and data. Reverting
   code does not automatically undo a database migration.

No broker keys or orders are part of this release policy. The application
remains research-only. Manual deployment does not enable demo/live orders.
Any future real-money order requires a supported provider, separately
protected credentials, server-owned risk checks and explicit positive owner
confirmation for that exact order.

Trading 212 documents its public API for Invest and Stocks ISA, not CFDs:
https://docs.trading212.com/api/section/general-information/api-limitations
