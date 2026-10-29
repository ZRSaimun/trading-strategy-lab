# Loop 4: durable PAPER risk reservation prototype (24 October 2026)

This module is **not an order execution service**. `backend/app/paper_risk_reservations.py` is deliberately **not imported into FastAPI routes or wired to the existing paper journal**. No broker connection, market quote, balance, real-money order, or demo broker order is created.

## Safety properties

- A new account starts with a persistent **kill switch ON**, a zero cap and no reservations. A missing, corrupt or stale account record is not trading permission.
- Each account has a single revision-controlled `Record` and an operation-tagged `Audit` row committed in the **same database transaction**. Audit actors are recorded as `paper-risk-store`, **not** an authenticated owner identity; no authentication has been established by this module. A conditional SQL UPDATE compares the complete previous record, rejecting stale concurrent writers. Initial creation relies on the unique primary key.
- Stressed cash-risk reservations use exact `Decimal` arithmetic from restricted decimal strings (maximum eight fractional places); no floating-point budget rounding. The sum cannot exceed the **owner-reviewed PAPER reservation cap**.
- Hashed client-order IDs remain in the account record, including after process restarts. Duplicates are rejected. At 500 IDs, the account fails closed rather than pruning history and accidentally accepting a replay.
- `engage_kill_switch` retries competing revisions up to 20 times and **persists an irreversible emergency latch**, even if the account was already disabled. Once latched, `set_policy(..., kill_switch=False)` is rejected at the database compare-and-swap boundary, including across restarts and with a current revision. If the write cannot be confirmed, the caller must stop accepting orders and escalate. There is deliberately no automatic unlatch/recovery operation.
- `load` verifies schema (now version 2 with a required boolean emergency latch), duplicate JSON keys, decimal syntax and a state checksum. The checksum detects accidental corruption but is **not tamper-proof cryptographic audit**. Account and client order IDs are not logged in cleartext.
- There is intentionally **no release, expiration, automatic reset or daily rollover**. Risk is not freed merely because an order was submitted or a stop was hit. A separate authenticated reconciliation against verified terminal position/order state must be designed before enabling lifecycle operations.

## Explicit limitations

The `owner_reviewed=True` method argument is **not authentication**. No public API calls these methods. Any future route must enforce the existing owner session, CSRF/origin protection, rate limiting, policy review and authorization, and must not allow a client to declare broker verification. This reserve cap is **not** the realized daily-loss circuit breaker, broker buying power, actual free margin, stop-gap guarantee, or per-order human approval.

The risk preview still accepts owner-declared quote and account inputs. No signed/executable bid/ask feed, verified position snapshot, authenticated demo brokerage, real PostgreSQL multi-worker race acceptance, journal integration, broker order sender, or live-order approval flow exists. Keep real-money execution completely disabled. CFD orders through Trading 212's public API are unsupported; its [official documentation](https://docs.trading212.com/api) describes Invest and Stocks ISA only.

## Verification and handoff

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_paper_risk_reservations.py
```

The thirteen isolated SQLite regressions cover default kill, cap exhaustion, restart/replay, stale revision, emergency kill, invalid money, corrupt JSON and transactional audit rollback. The new cases verify irreversible emergency stop, latching an already-disabled account and fail-closed rejection of a malformed latch even when its checksum is recomputed. They do **not** prove cross-worker PostgreSQL behavior. The optional PostgreSQL race harness in `tests/test_paper_journal_postgres.py` is for the separate journal and does not certify this module.

**Before integration:** run two independent PostgreSQL connections racing reservations and kill-switch writes in a disposable `test_*` database; simulate transaction interruption; integrate a single atomic account-wide paper risk reservation with the paper fill journal; implement a verified, audited release only after terminal reconciliation; require fresh authenticated bid/ask and positions; independently enforce daily drawdown, margin/leverage and per-order approval. Confirm Render production workspace, backup, rollback and post-deploy health before merging to auto-deploying `main`.

No profitability claim is made.

## Opt-in PostgreSQL acceptance (new)

The additional `backend/tests/test_paper_risk_reservations_postgres.py` harness requires a disposable PostgreSQL service; this branch's `postgres-reservations-acceptance` GitHub Actions job now supplies one. To exercise it, provision a **disposable local PostgreSQL database** whose name begins with `test_`, with a local host (`localhost`, `127.0.0.1`, or Docker host `db`) and no URL query options. Run:

```sh
cd backend
PAPER_RISK_TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/test_paper_risk' \
  PYTHONPATH=. python -m pytest -q tests/test_paper_risk_reservations_postgres.py
```

Do **not** commit credentials or point this at any production database. The harness creates and deletes only its own randomized schema. It races two independent PostgreSQL connections attempting £60 reservations against a £100 cap, expects exactly one successful compare-and-swap, verifies persisted kill-switch behavior, and injects an audit write failure to verify transaction rollback. A CI **skip is not a PostgreSQL pass**. Full acceptance still needs an actual disposable database, including crash/recovery and broker/journal reconciliation. No release or live execution is authorized by this test.

## Emergency-latch compatibility note

This draft introduces a version-2 risk-state envelope. Version-1 prototype records fail closed on load; **no automatic migration or policy re-enablement is provided**. Because the prototype is not connected to any production route or broker, a future integration must explicitly design and test authenticated migration/recovery before using existing persisted prototype data. The PostgreSQL harness now also rejects attempted policy re-enablement after an emergency stop, but it remains opt-in and **not certified** until actually executed against a disposable local PostgreSQL database. Do not merge/deploy without owner-approved production rollback and health checks.


## Reservation audit traceability (24 October 2026)

Every committed compare-and-swap audit now records the **exact decimal cap**, reservation count and total reserved cash. Successful reservation operations additionally record a SHA-256 digest of the client order ID, never the cleartext order ID. This lets an authorized future reconciliation workflow correlate a stored reservation with its audit entry without placing the raw client order ID in audit details. Two new SQLite regression tests check the digest, decimal precision, absence of raw identifiers, and that rejected replay attempts do not mutate state or emit a misleading successful CAS audit. The digest is **not an authenticated broker order receipt** and may be brute-forced for low-entropy identifiers; no user-identifying or secret IDs should be used as client order IDs. The current account hash and digest are not a tamper-proof audit trail. No order release, broker connector or execution path is introduced.


## Read-only remaining capacity and execution-denial contract (24 October 2026)

`load(account_id)` now exposes `remaining_risk_capacity_cash` as an **exact Decimal-derived string** (`limit_cash - reserved_cash`) without rounding. This is an accounting snapshot, not verified buying power, daily-loss headroom, free margin, or permission to trade. The response explicitly includes **both** `may_execute_paper_order: false` and `may_execute_real_order: false`, including when the owner-reviewed paper reservation policy is enabled. Uninitialized accounts still return `None` and must be treated as disabled.

Two additional isolated SQLite regressions exercise eight-decimal precision, cap exhaustion, restart-safe snapshots, initial kill state, emergency latch, and the explicit no-execution flags. The full isolated SQLite suite now contains **15 tests**. This addition has no HTTP exposure, broker call, order release, journal integration, schema change, or production data migration. PostgreSQL concurrency and production rollback gates remain outstanding; do not merge or deploy solely on the basis of a green standard CI run.


## Emergency freeze and disabled-capacity clarity (24 October 2026)

The emergency latch now freezes **every** policy mutation, including a seemingly harmless cap update while the kill switch is already ON. This prevents a latched account's policy and audit state from drifting during incident response; it is not an unlatch mechanism. The ordinary non-emergency kill switch can still be changed by the existing owner-reviewed PAPER policy path, which is not authenticated and has no execution route.

A read-only snapshot retains `remaining_risk_capacity_cash` as the arithmetic difference between cap and reservations, but adds `reservable_risk_capacity_cash` equal to **zero** whenever the kill switch is active. This prevents consumers from mistaking a disabled account's positive accounting headroom for currently reservable cash risk. Even a positive reservable snapshot is **not** broker-verified buying power or permission to place an order; both execution flags remain false.

Two new isolated SQLite regressions cover disabled-account snapshots, rejected new reservations, restart consistency, emergency policy immutability and no misleading audit event for rejected changes. The isolated SQLite suite now has **17 tests**. The isolated PostgreSQL race/rollback harness passed in branch CI on 25 October 2026; crash/recovery, production rollback and broker reconciliation remain unverified. No broker calls, order sender, migration, route, credentials, production data or paid services are introduced. Keep this PR draft until the existing release gates are met.

## Enabled-policy persisted-state invariant (25 October 2026)

An enabled (`kill_switch: false`) paper reservation state must have a **strictly positive cash cap**, including when loaded from storage. A zero-cap enabled record is rejected as corrupt even when its unkeyed SHA-256 envelope checksum has been recomputed. The default initialized disabled state with a zero cap remains valid. This protects against contradictory persisted policy snapshots; a matching checksum is not authentication, and a positive cap is never execution permission.

One additional SQLite regression verifies fail-closed load, reservation and emergency-stop operations and absence of a misleading success audit when such a malformed snapshot is present. The isolated SQLite suite now contains **18 tests**. The isolated disposable PostgreSQL race/rollback test **passed (1 test)** in [GitHub Actions run 40189063532](https://github.com/ZRSaimun/trading-strategy-lab/actions/runs/40189063532), alongside backend **196 passed / 2 skipped**, frontend build/tests and both smoke jobs. This does not establish crash/recovery, broker reconciliation, signed quotes, daily account loss controls or production backup/rollback. **Keep this PR draft, unmerged and undeployed**.


## Persisted-envelope size limit (25 October 2026)

The disconnected PAPER reservation store now rejects stored JSON envelopes exceeding **64 KiB UTF-8**, before parsing or evaluating their SHA-256 checksum. The same bound applies when encoding newly generated states. This limits accidental or adversarially bloated persisted records (including otherwise valid JSON with excessive whitespace), while preserving the documented maximum of 500 hashed reservation IDs. A size failure is treated as **corrupt state**: no reservation, kill-switch transition, or success audit is written; callers must halt any prospective order path rather than interpreting the failure as permission.

Two synthetic SQLite/unit regressions cover oversized but otherwise valid-checksum JSON and a fully populated 500-reservation state. The limit is a local parser/resource safeguard, **not** source authentication, tamper-proof storage, broker reconciliation, or a trading-risk guarantee. Existing production/release blockers and draft-only status are unchanged.

## Retained-ID / revision consistency (25 October 2026)

The disconnected reservation store never releases or silently prunes an order ID. Each successful reservation adds exactly one retained ID and increments the account revision in the same audited transaction. Persisted state with **more retained IDs than committed revisions** is therefore impossible and is rejected before a read, new reservation, or emergency-latch write can succeed. This invariant also applies when a stored JSON checksum has been recomputed; the unkeyed SHA-256 checksum is not authentication.

One synthetic SQLite regression creates two legitimate reservations, rewrites the persisted revision to an impossible smaller value with a matching checksum, and verifies fail-closed load/reserve/emergency-stop and unchanged audit count. The valid 500-ID boundary remains supported. This is only a consistency check: it cannot detect every forged revision or establish external broker order identities, realized daily losses, quote authenticity, crash recovery, or tamper-proof audit. The prototype remains PAPER-only, disconnected, draft, unmerged and undeployed pending broker reconciliation, production backup/rollback and independent review.

## Cross-account envelope binding and main-branch reconciliation (25 October 2026)

The disconnected risk-state envelope now includes the SHA-256 digest of its **own account record key**. A record copied into another account's key fails closed on load, reservation and emergency-stop attempts, even when its original state checksum is valid. The digest is an accidental-cross-account mix-up guard, **not** a MAC, signature, authorization, or tamper-proof record: a malicious writer who can rewrite the record and recompute hashes remains outside this prototype's threat model. No raw account identifier is stored in the envelope.

One synthetic SQLite regression copies a legitimate enabled account envelope into a different initialized account, then checks rejection and absence of false success audit events. Existing standalone envelope helper tests now supply a record key explicitly. Old envelopes lacking the account binding fail closed; there is **no automatic migration** or implicit re-enablement. Do not use on existing persistent prototype records without a separately reviewed recovery plan.

This branch also incorporates the current main tree and retains both independent disposable PostgreSQL acceptance jobs (daily-loss and reservations), resolving the conflicting workflow additions without dropping either safety suite. These tests and GitHub CI are software acceptance, not proof of broker execution, quote provenance, realized loss control, or profitability. PR remains draft and unmerged; no Render deployment is authorized.


## Revision-zero provenance fence (29 October 2026)

The disconnected PAPER reservation state now enforces the only valid version-2 revision-zero snapshot: kill switch ON, emergency latch OFF, literal zero cash cap, and no reservations. An enabled or positive-cap policy, or an emergency latch, requires an audited committed transition and cannot legitimately appear at revision zero. The loader rejects contradictory imported states even if their unkeyed checksum is recomputed. Synthetic SQLite regression cases cover three forged revision-zero variants, fail-closed read/policy/reserve/emergency paths, unchanged audit history, and the valid first policy transition. This is an internal consistency check, **not** an authenticated event ledger or broker verification. The branch remains draft, PAPER-only, unmerged and undeployed; integration, real broker reconciliation, crash/recovery and production release gates remain outstanding.
