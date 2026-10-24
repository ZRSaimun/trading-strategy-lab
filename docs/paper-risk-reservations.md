# Loop 4: durable PAPER risk reservation prototype (24 October 2026)

This module is **not an order execution service**. `backend/app/paper_risk_reservations.py` is deliberately **not imported into FastAPI routes or wired to the existing paper journal**. No broker connection, market quote, balance, real-money order, or demo broker order is created.

## Safety properties

- A new account starts with a persistent **kill switch ON**, a zero cap and no reservations. A missing, corrupt or stale account record is not trading permission.
- Each account has a single revision-controlled `Record` and an `Audit` row committed in the **same database transaction**. A conditional SQL UPDATE compares the complete previous record, rejecting stale concurrent writers. Initial creation relies on the unique primary key.
- Stressed cash-risk reservations use exact `Decimal` arithmetic from restricted decimal strings (maximum eight fractional places); no floating-point budget rounding. The sum cannot exceed the **owner-reviewed PAPER reservation cap**.
- Hashed client-order IDs remain in the account record, including after process restarts. Duplicates are rejected. At 500 IDs, the account fails closed rather than pruning history and accidentally accepting a replay.
- `engage_kill_switch` retries competing revisions up to 20 times. If the write cannot be confirmed, the caller must stop accepting orders and escalate. It never treats a failed write as successful.
- `load` verifies schema, duplicate JSON keys, decimal syntax and a state checksum. The checksum detects accidental corruption but is **not tamper-proof cryptographic audit**. Account and client order IDs are not logged in cleartext.
- There is intentionally **no release, expiration, automatic reset or daily rollover**. Risk is not freed merely because an order was submitted or a stop was hit. A separate authenticated reconciliation against verified terminal position/order state must be designed before enabling lifecycle operations.

## Explicit limitations

The `owner_reviewed=True` method argument is **not authentication**. No public API calls these methods. Any future route must enforce the existing owner session, CSRF/origin protection, rate limiting, policy review and authorization, and must not allow a client to declare broker verification. This reserve cap is **not** the realized daily-loss circuit breaker, broker buying power, actual free margin, stop-gap guarantee, or per-order human approval.

The risk preview still accepts owner-declared quote and account inputs. No signed/executable bid/ask feed, verified position snapshot, authenticated demo brokerage, real PostgreSQL multi-worker race acceptance, journal integration, broker order sender, or live-order approval flow exists. Keep real-money execution completely disabled. CFD orders through Trading 212's public API are unsupported; its [official documentation](https://docs.trading212.com/api) describes Invest and Stocks ISA only.

## Verification and handoff

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_paper_risk_reservations.py
```

The eight isolated SQLite regressions cover default kill, cap exhaustion, restart/replay, stale revision, emergency kill, invalid money, corrupt JSON and transactional audit rollback. They do **not** prove cross-worker PostgreSQL behavior. The optional PostgreSQL race harness in `tests/test_paper_journal_postgres.py` is for the separate journal and does not certify this module.

**Before integration:** run two independent PostgreSQL connections racing reservations and kill-switch writes in a disposable `test_*` database; simulate transaction interruption; integrate a single atomic account-wide paper risk reservation with the paper fill journal; implement a verified, audited release only after terminal reconciliation; require fresh authenticated bid/ask and positions; independently enforce daily drawdown, margin/leverage and per-order approval. Confirm Render production workspace, backup, rollback and post-deploy health before merging to auto-deploying `main`.

No profitability claim is made.

## Opt-in PostgreSQL acceptance (new)

The additional `backend/tests/test_paper_risk_reservations_postgres.py` harness is intentionally skipped in ordinary CI. To exercise it, provision a **disposable local PostgreSQL database** whose name begins with `test_`, with a local host (`localhost`, `127.0.0.1`, or Docker host `db`) and no URL query options. Run:

```sh
cd backend
PAPER_RISK_TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/test_paper_risk' \
  PYTHONPATH=. python -m pytest -q tests/test_paper_risk_reservations_postgres.py
```

Do **not** commit credentials or point this at any production database. The harness creates and deletes only its own randomized schema. It races two independent PostgreSQL connections attempting £60 reservations against a £100 cap, expects exactly one successful compare-and-swap, verifies persisted kill-switch behavior, and injects an audit write failure to verify transaction rollback. A CI **skip is not a PostgreSQL pass**. Full acceptance still needs an actual disposable database, including crash/recovery and broker/journal reconciliation. No release or live execution is authorized by this test.
