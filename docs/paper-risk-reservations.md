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

Eight synthetic SQLite tampering variants cover forged prior cash/caps/order
digests across reserve, policy and emergency transitions; a separate positive
regression covers policy cap changes and exact eight-decimal cash. Invalid
receipts quarantine reservable capacity and prevent further audit mutations.
This verifies **only the adjacent self-attested receipts**, not the full
historical chain, signed broker evidence, actual losses or trade profitability.
No route, broker order, merge or deployment is enabled.


## Adjacent reservation identity provenance (30 October 2026)

The read-only audit-head preflight now requires a preceding `reserve` receipt's
SHA-256 client-order digest to exist among the account's **currently retained**
reservation IDs. When the latest transition is another reservation, its order
digest must differ from the predecessor's. This catches a syntactically valid
but invented predecessor identity and an impossible replay of the newest order
as its own predecessor. Three synthetic SQLite tampering cases check
fail-closed snapshots, blocked transitions, unchanged audit counts and
unaffected interleaved accounts; a positive case preserves legitimate
distinct reservations across policy changes and emergency stop.

This checks only the **adjacent self-attested** receipt, not the full audit
history or cryptographic broker identity. No raw client-order IDs, real market
prices, private data, order sender or production deployment are introduced.
Keep PR #26 draft until main integration, atomic journal reconciliation,
authenticated broker BID/ASK and positions, crash recovery and owner-approved
backup/rollback are independently verified.


## Exact adjacent reservation cash delta (30 October 2026)

When the latest audit transition is a `reserve`, its hashed order identity
must exist in the current retained reservation collection **and** the
previous checkpoint's reserved cash plus that order's exact `Decimal` amount
must equal the current total. Merely checking that the preceding total is
smaller was insufficient: a forged but plausible prior cash balance could
previously pass. Three synthetic SQLite tampering cases alter the preceding
total above or below the true amount while preserving a valid current state;
the resulting snapshots quarantine reservable capacity and all attempted
mutations fail without new audit entries. A separate account remains valid.
Existing precision regressions cover canonical eight-decimal cash values.

This is only adjacent self-attested audit consistency, not cryptographic
authentication, full historical reconciliation, broker-sourced positions,
or profitability evidence. Keep the PR draft, unmerged and undeployed.

## Bounded retained PAPER audit receipt parsing (30 October 2026)

The disconnected reservation preflight rejects an initialization or CAS
receipt whose retained JSON detail exceeds **4,096 UTF-8 bytes**, before JSON
object allocation. This applies to the latest and immediately preceding
same-account audit rows; oversized but otherwise valid JSON (including trailing
whitespace) fails closed. Snapshots quarantine reservable cash and mutations
cannot append new audit events. Boundary regressions preserve valid 4,096-byte
JSON and reject 4,097-byte and multibyte-overflow details.

This is a local parser/resource bound, **not** a database query-size limit,
authenticated audit history, complete-chain verification, broker reconciliation
or trade approval. No production migration, order, merge or deployment is authorized.


## Adjacent prior-envelope digest reconstruction (30 October 2026)

For revisions above one, the disconnected PAPER risk audit verifier now
reconstructs the immediately preceding persisted version-2 state from the
current retained reservation set and the predecessor receipt's cap, stop
flags and revision. A new reservation is removed from that reconstructed
prior set. The reconstructed **canonical account-bound envelope SHA-256**
must match the predecessor's recorded `state_sha256`. Previously, the
predecessor digest was not checked at all, so a plausible-looking prior
receipt could contain a mismatched hash or an altered old cap while the
current state and latest receipt still agreed.

Four synthetic SQLite tampering cases cover altered predecessor hashes
before reservation, policy and emergency transitions, plus a forged prior
cap during a legitimate cap change. A positive restart test covers tiny
eight-decimal reservations, a reviewed cap change, ordinary policy stop,
re-enablement and irreversible emergency stop. Failed verification sets
reservable capacity to zero, rejects subsequent mutations and preserves
audit history and unrelated accounts.

This is **adjacent consistency**, not a signed ledger or independently
authenticated broker receipt. Anyone with database write access can forge
a mutually consistent state and hashes. Full history, atomic paper journal,
crash recovery, verified broker BID/ASK and owner-approved release/rollback
remain blockers. Keep PR #26 draft, unmerged and undeployed.


## Historical receipt population census (30 October 2026)

The PAPER risk preflight now checks that the number of retained same-account
initialization/CAS receipts equals the stored revision plus one. A SQL COUNT
catches deleted early initialization/policy rows or extra old receipts even
when the latest two checkpoints match. SQLite regressions exercise these
fail-closed cases, unchanged rejected writes, and independent accounts.

This is **not** full-chain content verification, a bounded database scan,
cryptographic authentication, broker reconciliation, or trading approval.
Coordinated deletion and insertion can preserve the count. Keep PR #26 draft,
unmerged and undeployed pending main integration, atomic journal coupling,
verified broker BID/ASK and positions, crash recovery, and backup/rollback.


## Bounded historical revision sequence verification (30 October 2026)

A matching receipt count can conceal a coordinated deletion and replacement
of an older event. PAPER risk preflight now walks the **account-specific**
receipts in append order and verifies every retained revision from zero through
the persisted head, with the expected writer, operation shape, exact account
hash and bounded JSON parsing. It detects count-preserving older duplicates,
reordered revisions, foreign actors and oversized old details even when the
latest two receipts are unchanged. Four synthetic SQLite regressions assert
fail-closed capacity, blocked mutations, unchanged audit count and account
isolation.

The walk is deliberately capped at **4,096 receipts per account**. Accounts
exceeding that cap are quarantined rather than treated as verified; this is
a safety bound, not a production-scale audit architecture. Repeated full
history scans can be expensive. Older receipt fields are schema-checked but
not independently reconstructed against historical database snapshots, and
a database writer can still forge a consistent history. This does not
establish cryptographic integrity, atomic journal coupling, broker quote
authenticity or trading profitability. PR #26 stays draft; no merge/deploy.


## Historical CAS receipt plausibility gate (30 October 2026)

The bounded account-specific audit walk now validates the **types and basic financial/operation plausibility of every retained CAS receipt**, not just its revision, actor and field names. Older receipts with malformed or noncanonical cash, boolean-as-count values, invalid state SHA-256 digests, unexpected order digests, contradictory emergency latch flags, zero caps on enabled policies, or impossible reserved cash/count relationships fail closed. The latest two checkpoints retain their stronger state reconstruction and cash reconciliation checks. Six additional synthetic SQLite tampering cases cover old policy receipts while keeping the last two receipts untouched and the audit count unchanged; the existing valid interleaved-account regression remains.

This is **not** full historical financial reconstruction or cryptographic authentication: a coordinated database rewrite can still forge plausible receipts and hashes. The 4,096-receipt bound and repeated scan cost remain. No broker data, real prices, order path, production data, deployment or policy activation is introduced. Keep PR #26 draft and unmerged pending integration, broker reconciliation, crash recovery and rollback review.


## Historical PAPER receipt transition reconciliation (30 October 2026)

The bounded account-specific audit walk now checks **transitions between every retained CAS receipt**, not just whether each older receipt is individually plausible. Initialization must precede a policy change or a zero-cap emergency latch; reservations must follow an enabled policy, increase the retained count by exactly one, preserve the cap and increase reserved cash by the **exact Decimal amount of the matching retained order**. Policy and emergency transitions cannot silently change reserved cash or order counts; emergency stops cannot alter the cap or be followed by later CAS writes. Historical reservation hashes must be unique and must match the complete current no-release reservation population.

Six synthetic SQLite regressions cover plausible but inconsistent old cash totals, duplicate historical order identity, silent policy cash changes, reserve-time cap changes, count jumps and retroactive cap changes. They retain valid latest-two receipts and verify fail-closed capacity, blocked writes, unchanged audit count and unrelated-account isolation. Run `PYTHONPATH=. python -m pytest -q tests/test_paper_risk_audit_census.py` from `backend`.

**Limits:** All receipts and retained order amounts are self-attested in the same database. An actor able to rewrite all stored states, receipts and checksums can still forge a consistent chain. Historical receipt scanning is bounded to 4,096 entries and costs database work; the account is quarantined above that bound. No broker execution, journal integration, actual BID/ASK quote authentication, daily realized-loss verification, production migration, merge or Render deployment is authorized by these tests.


## Historical PAPER receipt digest reconstruction (30 October 2026)

The bounded account-specific audit walk now reconstructs the exact retained
reservation prefix at **every** historical CAS revision and verifies each
receipt's `state_sha256` against the canonical version-2 envelope at that
revision. It also reconciles each old reserved-cash total against its prefix.
Older policy/reservation receipts with plausible but incorrect checksums
cannot hide behind two intact latest checkpoints. Three synthetic SQLite
tampering cases and one positive precision/restart/emergency regression
are in `backend/tests/test_paper_risk_historical_digests.py`.

These are **self-attested** database digests, not signed evidence: a database
writer can rewrite a coordinated history. Full-history scans remain bounded
to 4,096 receipts and add cost. This does not authenticate broker quotes,
reconcile orders or positions, prove crash recovery or authorize execution.
PR #26 remains DRAFT / PAPER ONLY / NO MERGE / NO DEPLOY without separate
approval and all documented evidence gates.

## Canonical retained audit receipts (30 October 2026)

The disconnected PAPER reservation verifier now requires each retained account-specific audit JSON receipt to match the exact canonical encoding emitted by the store (sorted keys, compact separators, canonical JSON escaping and numeric spelling). A receipt with identical decoded fields but changed whitespace, escaped key names or field order is no longer accepted as unchanged evidence. This check applies to historical receipts as well as the latest two checkpoints, after the existing 4,096-byte size preflight and duplicate-key validation.

Seven synthetic SQLite cases in `backend/tests/test_paper_risk_canonical_audit.py` cover three byte-only alterations at an older and latest receipt, blocked reservations/policy/emergency writes, unchanged audit count, unaffected unrelated account, and legitimate restart/emergency transitions. Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_paper_risk_canonical_audit.py`. Canonical formatting is **not** a signature, trusted timestamp, append-only ledger or proof of external broker authenticity: a database writer able to forge both receipts and their unkeyed checksums can still fabricate a consistent history. Existing source, journal, crash-recovery, main-branch integration and owner-approved deployment blockers remain. **DRAFT / PAPER ONLY / NO MERGE / NO DEPLOY / NO ORDERS.**

## Canonical persisted PAPER account envelopes (30 October 2026)

The disconnected reservation store now rejects a byte-rewritten persisted
account envelope even when its parsed fields and inner state checksum are
unchanged. Every store-generated envelope uses canonical sorted-key, compact
JSON; `_decode` requires the retained bytes to match that encoding before
validating the account, state and checksum. This also protects revision-zero
initialization snapshots, whose initialization audit receipt does not carry a
state-envelope digest. Noncanonical states raise a corrupt-state error and
block all reservation, policy and emergency mutations without adding audit
receipts. Six synthetic SQLite regressions cover whitespace, escaped-key and
key-order rewrites at revisions zero and two; a positive restart/precision/
emergency regression preserves valid store-generated envelopes. An existing
checksum-without-audit regression now writes canonical forged bytes so it
continues to exercise the separate audit-mismatch gate.

Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_paper_risk_canonical_envelope.py tests/test_paper_risk_reservations.py`.
This is **not** a cryptographic signature, trusted external ledger, broker
reconciliation, or proof of market-data authenticity or trading performance.
A database writer can still forge a mutually consistent canonical history.
PR #26 remains DRAFT / PAPER ONLY / NO MERGE / NO DEPLOY / NO ORDERS.


## Unknown-action PAPER audit receipt census (30 October 2026)

The bounded account-specific audit verifier now considers **every** retained
receipt whose detail contains the exact canonical `account_hash` field, not
only receipts already labelled `paper.risk.init` or `paper.risk.cas`.
An unrecognized action carrying that account hash therefore invalidates the
expected revision population and quarantines reservable capacity. Previously,
a foreign/unknown action could be inserted without affecting the known-action
census. Three synthetic SQLite regressions cover an unexpected action before
the initialization receipt, after the latest CAS, and an unrelated action name;
blocked policy/reservation/emergency writes and unrelated-account isolation
are asserted in `backend/tests/test_paper_risk_unknown_actions.py`.

Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_paper_risk_unknown_actions.py`.
This remains a **self-attested** audit: the exact-text account-hash locator
cannot discover a forged receipt that omits or rewrites the field, and a
privileged database writer can rewrite coordinated evidence. It does not
prove broker authenticity, complete audit integrity, crash recovery,
positive expectancy, or permission to execute. **DRAFT / PAPER ONLY / NO MERGE /
NO DEPLOY / NO ORDERS.**


## Bounded SQL audit-detail preflight (30 October 2026)

Before loading any account-specific PAPER audit receipt text into Python, the read-only verifier now asks SQLite/PostgreSQL whether a matching retained row exceeds **4,096 characters**. If so, it fails closed without fetching that oversized detail or calling the JSON parser. This reduces memory exposure from malformed or adversarially inflated audit rows. The existing `_audit_json` parser separately enforces **4,096 UTF-8 bytes** (and canonical encoding) because SQL `length()` measures characters, not UTF-8 bytes. The SQL check is an early rejection, not a replacement for the byte bound.

`backend/tests/test_paper_risk_audit_sql_size_preflight.py` uses a synthetic 1 MiB same-account audit row to prove that the verifier never reaches Python JSON parsing or loads an Audit ORM row before denying capacity. It also verifies blocked reservation/policy/emergency writes, unchanged audit count, account isolation, and a multibyte UTF-8 row whose character count passes SQL but whose byte count must fail the parser. All fixtures are synthetic; no raw broker data or secrets are included.

This is **resource hardening**, not a cryptographic audit signature, authenticated broker reconciliation, full audit provenance, or a profitability claim. The database must still evaluate the account-hash text match and SQL length expression; this does not bound database-side scanning, validate receipts that omit the account locator, or make the disconnected prototype suitable for execution. Keep PR #26 draft, paper-only, unmerged and undeployed until its integration and independent evidence gates are satisfied.


## SQL-side persisted-state envelope size preflight (30 October 2026)

The disconnected PAPER risk store now uses a **single SQL CASE/length projection** to refuse oversized persisted account envelopes **before** their text is transferred into Python. The guard covers read-only snapshots, audit verification, reservation/policy transitions, and emergency-stop reads. An absent account is still treated as missing, whereas an oversized or NULL-valued existing record raises a corrupt-state error and cannot produce a successful write. The existing 64 KiB UTF-8 byte check remains in `_decode`: SQLite/PostgreSQL SQL `length` counts characters, not bytes. The single-statement projection avoids a separate preflight/fetch race, although it cannot prevent all concurrent state changes after a read; the existing conditional CAS remains necessary.

Two synthetic SQLite regressions in `backend/tests/test_paper_risk_state_sql_size_preflight.py` cover a 1 MiB malformed record (asserting the Python decoder is never invoked and no audit/write succeeds), and multibyte text under the SQL character limit but over the UTF-8 byte limit. The other account stays independently readable. This is **resource-bound hardening only**, not a signature, authenticated audit, verified broker state, crash-recovery proof, or permission to execute orders. Keep PR #26 **DRAFT / PAPER ONLY / NO MERGE / NO RENDER DEPLOY** pending the documented integration and owner-approval gates.

## Refuse revision-zero resurrection over retained PAPER audit history (31 October 2026)

`initialize()` now checks the same account-hash audit locator used by the
historical verifier **before** inserting a new revision-zero state. If a state
row has disappeared but its prior initialization, policy, or reservation audit
receipts remain, initialization returns `False` without changing state or
audit. An unknown-action receipt bearing that same account hash also blocks
first initialization. This prevents a false report of successful fresh setup
over contradictory retained evidence; it does **not** repair the missing state
or grant permission to reserve. Four synthetic SQLite regressions in
`backend/tests/test_paper_risk_orphan_initialization.py` exercise the orphan
cases, unchanged audit population, blocked subsequent operations and
unrelated-account isolation.

Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_paper_risk_orphan_initialization.py`.
The account-hash match is a self-attested exact-text locator, **not** an
authenticated append-only ledger. Records that omit or obfuscate that field
can remain invisible, and concurrent foreign audit writes are not serialized
by this preflight. No broker evidence, profit, crash-recovery certification,
live orders, merge or Render deployment is established. Keep PR #26 **DRAFT /
PAPER ONLY / NO MERGE / NO DEPLOY / NO ORDERS**.


## Bounded audit-history emergency-stop slot (31 October 2026)

The PAPER audit verifier deliberately caps per-account retained history at 4,096 receipts. Previously an ordinary policy/reservation CAS at revision 4,095 could create revision 4,096 (4,097 receipts), after which the verifier would refuse all further state changes, including the durable emergency stop. The disconnected store now reserves the final verifiable revision for `emergency_kill`: ordinary transitions stop at revision 4,094, and an emergency latch may advance that state to revision 4,095. The read-only `reservable_risk_capacity_cash` reports zero when the ordinary transition budget is exhausted, even if arithmetic cash headroom remains positive. An already-latched emergency retry remains idempotent and audit-checked.

Two synthetic SQLite regressions reduce the cap to five receipts to exercise the exact boundary, restart continuity, absence of misleading writes, emergency-latch persistence and unrelated-account isolation. This is a finite audit-resource and fail-closed accounting safeguard, **not** authenticated broker evidence, verified daily loss control, a tamper-proof audit, or permission to submit paper/real orders. Accounts already at an exhausted legacy revision still require manual reconciliation; no automatic reset, pruning or unsafe un-latch is provided. Keep PR #26 draft, unmerged and undeployed pending the existing integration and production-readiness gates.


## SQL-side UTF-8 octet bounds for PAPER audit and state (31 October 2026)

SQLite `length(TEXT)` counts Unicode characters and **stops at an embedded NUL**. The earlier SQL character-count preflight could therefore materialize a 1 MiB NUL-padded state or audit receipt before the Python byte check rejected it. Multibyte UTF-8 text also bypassed the SQL character threshold. Both PAPER-only preflights now count actual bytes: SQLite uses `length(CAST(text AS BLOB))`, and PostgreSQL uses `octet_length(text)`. Unsupported dialects fail closed. The existing Python UTF-8 byte, canonical JSON and audit-history checks remain independent defenses.

Four synthetic SQLite regressions in `backend/tests/test_paper_risk_sql_octet_preflight.py` exercise NUL-padded and multibyte over-limit state envelopes and audit receipts, asserting rejection **before** Python decoding/parsing, no successful risk writes, unchanged audit counts and unrelated-account isolation. The pre-existing SQL-size tests also retain coverage. This fixes a resource/materialization gap; it does **not** authenticate audit records, bound all database-side scan costs, verify broker BID/ASK or positions, or prove profitability. Keep PR #26 **DRAFT / PAPER ONLY / NO MERGE / NO DEPLOY / NO ORDERS** pending independent PostgreSQL acceptance, journal atomicity, crash recovery and owner release approval.

## 31 October 2026 — SQL preflight for retained audit actor/action metadata

The account-specific audit verifier now rejects **unexpected actors and action names in SQL before fetching any historical ORM audit rows**. SQLite does not enforce the declared `String(80)` length for these columns, so a corrupt or adversarial actor/action can otherwise carry megabytes (including embedded NUL characters) into Python before the existing history verifier rejects it. The SQL check covers the **entire located account history**, including older receipts; it does not assume the latest two records suffice.

Four synthetic SQLite regressions mutate an older initialization receipt's actor/action with 1 MiB or NUL-suffixed text. They verify that JSON parsing is not reached, snapshots report zero reservable capacity, reservations/policy/emergency writes fail closed without new audit records, and another account remains unaffected. This is **resource safety and self-attested audit consistency**, not authenticated broker evidence or tamper-proof storage. The account locator still depends on the exact canonical hash field; omitted/obfuscated hashes remain outside this check. Keep PR #26 draft, PAPER-only, unmerged and undeployed.


## Retained PAPER audit timestamp schema preflight (31 October 2026)

The disconnected reservation verifier now rejects same-account retained audit
rows whose timestamp is zero, negative or NULL **in SQL before reading the
audit receipt**. SQLite's permissive INTEGER affinity can also store arbitrary
text, so the SQLite preflight checks the actual `typeof(time)` is `integer`.
PostgreSQL already enforces the INTEGER column type. Three synthetic SQLite
regressions in `backend/tests/test_paper_risk_audit_time_preflight.py` corrupt
an **older** initialization timestamp while leaving the latest policy receipt
untouched; read-only capacity fails closed, policy/reservation/emergency writes
are blocked, audit counts remain unchanged and an unrelated account remains
usable. Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_paper_risk_audit_time_preflight.py`.

This is only a local audit **schema-consistency** check, not a trusted time
source. Positive forged timestamps, clock drift, reordered real-world events
and coordinated database rewrites are not authenticated or ruled out. No broker
receipts, real orders, data releases, main merges or Render deployments are
introduced. Keep PR #26 DRAFT / PAPER ONLY / NO MERGE / NO DEPLOY.


## Historical cash representation integrity (31 October 2026)

The bounded PAPER audit-history verifier now compares each retained `reserved_cash` text with the exact `str(Decimal)` cumulative amount reconstructed from retained reservation strings, rather than accepting merely numerically equal values. An older policy receipt rewritten from `0` to `0.00` or `0E+999999999`, or a reservation receipt rewritten from `1` to `1.0`, fails closed even if the latest checkpoint is unchanged. Legitimate decimal scale and tiny `1E-8` reservations remain accepted. Five isolated synthetic SQLite regressions cover both tampering and positive restart/emergency behavior in `backend/tests/test_paper_risk_audit_cash_representation.py`. This detects textual inconsistency, **not** cryptographic forgery; a database writer can still rewrite multiple mutually consistent self-attested records. No broker evidence, orders, execution route, merge or deployment is added.


## Nonpositive historical audit-ID preflight (31 October 2026)

The disconnected PAPER risk verifier now rejects same-account audit rows with
zero or negative primary-key IDs in SQL, **before** retrieving or parsing their
JSON receipts. Normal store writes use positive auto-generated IDs. A manual
rewrite of an older initialization row's ID could previously preserve receipt
count, JSON, revisions and order while still passing verification; it must now
quarantine the account rather than authorize further PAPER reservations or
policy changes. Four synthetic SQLite regressions cover zero/negative IDs
both before and after policy/reservation transitions, rejected writes,
unchanged audit counts and unrelated-account isolation. This is a local
consistency check, **not** an authenticated append-only ledger, broker evidence,
or a trading-profitability claim. Keep PR #26 draft, unmerged and undeployed.


## Fail-closed audit clock preflight (31 October 2026)

Before inserting a PAPER account or updating a persisted PAPER reservation/policy/emergency state, the store now checks that its own wall-clock reading can be represented as a **positive integer epoch second**. A zero, negative, fractional value truncating to zero, NaN, infinity or nonnumeric clock reading raises a fail-closed error **before any state or audit write**. This prevents an invalid local clock from committing a receipt that the historical SQL verifier would immediately reject, potentially stranding a newly initialized account or an emergency stop. The preflight is not a trusted time source, monotonicity guarantee, event-calendar validation, broker receipt or order authorization.

The synthetic SQLite regression suite `backend/tests/test_paper_risk_audit_clock_preflight.py` covers initialization, owner-reviewed policy, reservations, emergency latch, unchanged rows on rejection, unaffected other accounts, and successful recovery once the clock is valid. PostgreSQL and crash-recovery certification remain separate integration gates. The module is still disconnected from any order sender and remains **PAPER ONLY / NO MERGE / NO DEPLOY**.


## PostgreSQL INT4 audit-clock boundary (31 October 2026)

The disconnected PAPER reservation store writes audit epoch seconds into the existing
`Audit.time` SQLAlchemy `Integer` column. PostgreSQL's integer column has a
signed 32-bit maximum of **2,147,483,647** (19 January 2038 UTC), whereas
SQLite permits larger integers. The writer now rejects out-of-range epoch
values **before any state/audit mutation**. Historical verification also
rejects retained account receipts above that bound, including when SQLite
otherwise accepts them. Synthetic SQLite regressions cover overflow at
initialization, reservation and emergency latch, a corrupted older receipt,
unrelated-account isolation, and the inclusive upper boundary.

This is a **fail-closed compatibility guard, not a year-2038 solution**.
A separately reviewed migration to a wider timestamp column is required
before this boundary; until then the store must refuse new writes rather
than report a durable stop that PostgreSQL could not store. The local clock
remains untrusted, and no broker or execution path is enabled.


## Reject identical PAPER policy revisions (31 October 2026)

Repeated `set_policy` calls with the same **exact cash-cap text** and the same kill-switch value now return `False` without advancing the persisted revision or appending an audit receipt. This preserves the bounded 4,096-receipt history for actual risk changes and its reserved final emergency-stop slot. The owner-review flag is still **not authentication**. Different decimal text (for example, `100` versus `100.00`) remains an explicitly audited change; historical no-op receipts remain readable for compatibility. Synthetic SQLite regressions cover initialized, enabled, reserved and near-capacity accounts, unchanged receipts across restarts, account isolation, a durable emergency latch and exact-text policy changes. This is internal PAPER accounting safety, **not** broker reconciliation, an executable order path, cryptographic audit evidence or profitability.


## Idempotent emergency latch: same-session checkpoint verification (31 October 2026)

An already-latched PAPER account now checks the **exact bounded state envelope and
audit history read in its existing database session** before acknowledging an
idempotent emergency-stop retry. Previously it closed the state-reading session
and called a separate read-only verifier, which could inspect a different
checkpoint after concurrent modification. The single-session path also avoids
an unnecessary extra database session. Two synthetic SQLite regressions in
`backend/tests/test_paper_risk_latched_snapshot.py` check single-session
idempotency, unchanged audit receipts, fail-closed noncanonical history and
recovery only after manual restoration of the original valid receipt.

This is a narrower read-consistency guarantee, **not** a serializable snapshot:
PostgreSQL READ COMMITTED still permits concurrent changes between statements,
and self-attested audit hashes do not authenticate broker positions or receipts.
No orders, live permissions, production writes, merge or Render deployment.
Keep PR #26 **DRAFT / PAPER ONLY / NO MERGE / NO DEPLOY**.

## Fractional audit-clock INT4 boundary (31 October 2026)

The disconnected PAPER risk store now checks the **untruncated** local epoch against the PostgreSQL signed-32-bit audit-time maximum before converting it to integer seconds. Previously, a clock reading such as `2147483647.25` could truncate to the apparently valid `2147483647`, despite already being beyond the supported database time range. Synthetic SQLite regression cases reject fractional overflow during initialization, reservation and emergency-stop writes without creating state or audit receipts, while confirming that fractional values strictly below the maximum remain usable. This is a fail-closed portability guard, **not** a trusted clock, broker receipt, year-2038 migration, or permission to execute trades.


## Per-account local-clock rollback fence (31 October 2026)

For **new PAPER policy and reservation transitions**, the disconnected store now requires the writer's valid integer audit epoch to be at least the timestamp of the latest retained receipt for that account. A local clock rollback fails closed **before** updating the state row or appending a success audit. Equal-second timestamps are permitted because multiple legitimate operations may occur within one second. The comparison is account-local; one account's future-dated checkpoint cannot freeze another account.

**Emergency stop remains exempt from the nondecreasing-clock check** so an already-enabled account can still persist its irreversible emergency latch when its local clock moves backward. The receipt remains a local timestamp, not trusted chronological evidence. Historical verification deliberately does not reinterpret pre-existing clock regressions as proof of tampering. Two synthetic SQLite regressions cover denied policy/reservation writes with unchanged state and audit counts, restart-safe verification, equal-second transitions, unrelated-account isolation and a durable emergency latch despite rollback. The test is software-only: no trusted clock, authenticated broker quote, journal integration, market-data acceptance, or profitable strategy is established. Keep PR #26 draft, paper-only, unmerged and undeployed pending the existing integration and release gates.
