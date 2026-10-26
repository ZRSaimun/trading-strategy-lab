# Paper daily-loss persisted-state bounds (Loop 4)

The existing disconnected `PaperDailyLossBreaker` stores caller-declared, **unverified** paper P&L observations in the shared `Record` table. Its UTC-day, revision, sequence and monotonic peak-loss checks are retained.

## Change

- Before JSON parsing, require the stored record to be a string no larger than **8,192 UTF-8 bytes**. Even syntactically valid JSON with excessive trailing whitespace fails closed.
- Require the schema `version` to be exactly the integer `1`; JSON `true` and `1.0` must not be treated as schema version 1.
- Existing invalid-state handling remains `ValueError` with manual recovery; the state and audit log are not changed by rejected observations.
- Synthetic regression cases cover forged versions and oversized valid JSON whitespace, including failed reads and updates.

## Boundaries and release

These checks protect a parser from oversized/corrupt persisted values; they are **not** tamper-proof storage, signed P&L evidence, authenticated broker inventory, a loss guarantee or permission to trade. A database writer can still alter values; authoritative broker reconciliation and a transactionally consistent admission workflow remain outstanding. No broker, credential, HTTP route, schema migration, execution adapter or deployment is introduced.

Keep the change in a draft PR until the latest exact-head CI passes and the target production environment has a confirmed restorable backup, rollback plan and post-deploy health verification. The open reservation integration in PR #26 and read-only cross-store preflight in PR #111 remain separate and are not merged by this change.
