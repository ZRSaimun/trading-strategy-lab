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


## First-reservation post-policy revision fence (30 October 2026)

The initialized PAPER account is disabled at revision zero. A reservation cannot be the first successful transition: at least one committed policy change must precede it. Persisted envelopes now require **retained reservation count <= revision - 1** (and zero reservations at revision zero), in addition to the existing cash cap and emergency-latch invariants. This rejects a checksum-recomputed revision-one record claiming a reservation even though no enabling policy transition could have occurred. The supported 500-ID synthetic boundary requires at least revision 501. A regression checks the valid first policy/reservation sequence, then verifies fail-closed read, policy, reservation and emergency-stop paths and unchanged audit counts after a forged revision.

This is a narrow consistency check, **not** proof of an authenticated or complete audit ledger; a writer able to alter stored state and recompute its unkeyed checksum may still forge a plausible revision. No broker, order sender, release operation, production data or Render deployment is involved. Keep PR #26 draft and unmerged until verified broker reconciliation, journal integration, backup/rollback and owner-approved release gates exist.


## Disabled-account stop revision integrity (30 October 2026)

A retained reservation can only be created while the PAPER kill switch is OFF. Therefore a stored state that is **currently disabled** and still retains reservations needs one **additional committed revision after the reservation population** for an ordinary policy stop or emergency stop: `revision >= reservation_count + 2`. A checksum-recomputed snapshot claiming one reservation and a stop at revision two is rejected before reads or writes can proceed. Separately, a positive-cap **emergency latch** requires a prior policy transition and a distinct emergency transition (`revision >= 2`); an immediate zero-cap emergency at revision one remains valid. The 500-ID synthetic disabled boundary now uses revision 502; an enabled account with 500 reservations may still be valid at revision 501.

Parameterized SQLite regressions cover forged ordinary/emergency stops, a forged positive-cap revision-one emergency latch, rejected read/policy/reservation/emergency paths with unchanged audit history, and valid sequential stops. These are internal consistency fences, **not** an authenticated audit chain: an attacker who can rewrite stored state and its unkeyed checksum may still forge plausible history. No broker receipts, real account loss, signed quotes, orders, migration or production changes. Keep PR #26 draft, unmerged and undeployed until independent broker reconciliation, journal integration, crash recovery, and owner-approved backup/rollback verification.


## Read-only account audit-head consistency preflight (30 October 2026)

`PaperRiskReservationStore.verify_audit_head(account_id)` checks that the most recent retained per-account `paper.risk.init` or `paper.risk.cas` audit row agrees with the persisted record's revision, kill state and, after initialization, the exact outer-envelope SHA-256, emergency latch, cap, reserved cash, reservation count and last reservation digest. Missing or inconsistent evidence returns `False`; corrupt stored envelopes still raise and must fail closed. This check does **not** change the account, create a success audit, authorize a paper order, or activate an endpoint. Synthetic SQLite regressions cover initialization, policy/reservation/emergency transitions, independent accounts, checksum-recomputed state edits and inconsistent/missing audit heads.

This is a **read-only diagnostic**, not a cryptographic or tamper-proof audit chain: someone able to rewrite both the state and audit can forge both, and the audit rows do not yet establish authenticated owner identity. Concurrent commits between the two reads can produce a conservative false result; a stable, isolated database snapshot and independently verified external broker/journal receipts are required before any integration. `load`, `reserve` and `set_policy` do not implicitly call this diagnostic, and all execution permission flags remain false. Keep PR draft, disconnected, unmerged and undeployed.

## Mutation-time audit-head fence (30 October 2026)

Before any PAPER reservation, owner-reviewed policy change or emergency-stop compare-and-swap, the store now checks the retained account-specific audit head against the decoded state **inside the same database transaction**. A missing or inconsistent head raises a fail-closed error rather than permitting a new risk-state transition. An already-emergency-latched retry also requires a corroborating head before reporting success. The read-only diagnostic remains available; ordinary `load` still decodes the envelope without asserting audit authenticity. SQLite regressions cover a checksum-valid state with a corrupted audit head, a missing initialization audit, and an already-latched account whose emergency audit was deleted. Rejected operations do not append a misleading success audit.

This is **not** a cryptographic audit chain, broker reconciliation or authenticated owner approval. A writer who can forge both state and audit can still defeat it; concurrent independent audit tampering and actual process-kill recovery are not certified. No order route or broker sender is enabled. PR #26 remains draft, unmerged and undeployed pending independent production and market-evidence gates.

Audit cash totals are compared to the exact canonical `str(Decimal)` representation produced by the writer, rather than parsing them as user-supplied money. This preserves fail-closed exactness for valid eight-decimal micro-reservations whose canonical audit total is `1E-8`. The strict user-input cash grammar is unchanged; the existing capacity regression now explicitly checks that the micro-reservation audit verifies before the next legitimate reservation.


## Audit writer and exact event-schema fence (30 October 2026)

The mutation-time and read-only audit-head checks now require the retained
account-specific audit row to have actor `paper-risk-store` and the **exact**
fields emitted by this prototype's initialization or compare-and-swap writer.
Unknown or missing event fields, and a matching-looking event attributed to
another actor, fail closed. Six parameterized synthetic SQLite regression cases
cover foreign actors, unexpected fields and missing fields at both revision
zero and a committed policy revision. Failed policy, reservation and emergency
transitions leave the account and audit count unchanged.

This only rejects accidental schema drift and some malformed/foreign audit
records. The actor string is **self-declared, not authenticated**; the database
audit is neither signed nor immutable. A writer who can rewrite both account
state and audit history can still forge a matching event. This change does not
supply broker reconciliation, atomic coupling to the paper journal, executable
quotes, process-death recovery or live trading permission. Keep PR #26 draft,
unmerged, disconnected and undeployed pending independent release evidence.

## Audit operation/state coherence (30 October 2026)

The opt-in PAPER risk-store audit-head verifier now checks that the declared
operation could have produced its checkpoint: a `reserve` event requires an
enabled, non-emergency-latched account and a retained hashed order ID; an
`emergency_kill` event requires both the kill switch and emergency latch; and
a `policy` event cannot claim an emergency latch. Policy and emergency events
must not carry a reservation-order digest. Three synthetic SQLite regressions
replace otherwise schema-valid, checksum-matching audit operations and verify
that preflight, reservations, policy writes and emergency retries fail closed
without creating another audit event. This is internal consistency only:
the audit remains unkeyed/self-attested, not authenticated broker evidence,
an execution permission, or a substitute for journal reconciliation.
Keep the draft unmerged and undeployed pending the existing release gates.

## Fail-closed read-only capacity on audit mismatch (30 October 2026)

The disconnected PAPER `load(account_id)` snapshot now reports `audit_head_verified` (a local, **self-attested** latest-checkpoint consistency result). The snapshot and latest same-account audit are inspected within one database session. If the checkpoint is absent, malformed, or disagrees with the stored state, `reservable_risk_capacity_cash` is **"0"**, even when the stored kill switch is off. `remaining_risk_capacity_cash` remains a clearly separate arithmetic balance, **not** usable risk or broker buying power. Both execution flags stay false in every case. An uninitialized account still returns `None`; corrupt state still raises rather than being repaired or silently accepted. A concurrent writer can cause a conservative false negative; no positive audit result is trading authorization. Synthetic SQLite regressions cover missing and altered latest audits, preserved accounting totals, blocked reservations, restart-safe reads and a valid emergency stop. This does not authenticate an audit writer, validate broker positions, or authorize deployment or orders.


## Adjacent audit-revision continuity guard (30 October 2026)

The PAPER risk-state audit preflight now inspects the **two latest same-account risk audit rows**, rather than accepting a matching final row alone. Revision zero must have exactly one initialization event. At a positive revision, the immediately preceding retained event must have the exact previous revision, expected initialization/CAS action, designated writer and expected basic event schema. A deleted predecessor, duplicate/replayed latest event or rewritten predecessor revision now fails closed: read-only snapshots report `audit_head_verified: false` and zero *reservable* capacity, while policy/reservation/emergency mutations refuse to commit. Other accounts' interleaved events do not count as predecessors.

Synthetic SQLite regressions cover all three tampering modes, a duplicate initialization event, unchanged audit history after blocked mutations, and independent-account isolation. This is **only an adjacent continuity check**, not a verification of the entire historical chain, event authenticity, tamper resistance, broker reconciliation, cash-loss enforcement or profitability. A writer able to forge both records and events remains outside the guarantee; historical pruning of these required events must be treated as a safety stop, not an invitation to regenerate them. PR #26 stays draft, disconnected, unmerged and undeployed.

## Adjacent PAPER audit transition semantics (30 October 2026)

The latest two same-account risk audit checkpoints now receive a **causal transition consistency** check in addition to their revision/schema checks. The immediately preceding CAS must have a typed, bounded retained-reservation count, typed stop flags, and a reachable non-emergency state. A previous emergency latch cannot be followed by another mutation; a preceding reservation cannot claim to have occurred while disabled. The current reservation event must add exactly one retained order identity relative to that predecessor; policy and emergency transitions must retain the same count. A reservation also cannot directly follow a disabled checkpoint without an intervening enabling policy transition.

Five parameterized SQLite tampering regressions cover incorrect or boolean predecessor counts, forged previous stop/latch flags and a retroactively renamed emergency event. A sixth test checks unchanged reservation population across a subsequent policy stop. Failed preflights quarantine reservable capacity and reject reservation/policy/emergency writes without appending audit events. This is **adjacent self-attested continuity only**, not full historical audit-chain verification, a cryptographic signature, broker reconciliation, independently authenticated quotes, a live-order permission or evidence of profitable trading. PR #26 stays **DRAFT / NO MERGE / NO DEPLOY / NO ORDERS** pending main integration, atomic journal coupling, crash recovery and authorized market/broker evidence.

## Adjacent audit cash/cap conservation (30 October 2026)

The disconnected PAPER reservation preflight now checks the **immediately preceding**
same-account CAS receipt for canonical, finite nonnegative Decimal reserved cash
(including legitimate `1E-8` notation), a valid positive cap when enabled,
reserved cash not exceeding its cap, and agreement between zero/nonzero
reserved cash and the retained reservation population. Prior reservation
receipts must contain a SHA-256-shaped order digest; non-reservation receipts
must have a null order digest. Across an adjacent transition, `reserve` must
increase reserved cash and retain the identical cap; `policy` and
`emergency_kill` must preserve reserved cash, and an emergency stop cannot
change the cap. Owner-reviewed policy cap changes remain allowed.

Seven synthetic SQLite tampering variants cover forged prior cash/caps/order
digests across reserve, policy and emergency transitions; a separate positive
regression covers policy cap changes and exact eight-decimal cash. Invalid
receipts quarantine reservable capacity and prevent further audit mutations.
This verifies **only the adjacent self-attested receipts**, not the full
historical chain, signed broker evidence, actual losses or trade profitability.
No route, broker order, merge or deployment is enabled.
