# Disconnected paper stop-coverage review (research only)

`backend/app/paper_stop_coverage_review.py` reviews **caller-declared, untrusted** open-position and protective-stop snapshots. It performs no I/O, broker calls, paper fills, journal writes, risk-reservation releases, or live orders. Its decision is **always `HOLD_RECONCILIATION`**, even if all structural checks match. It cannot establish a broker accepted or retained a stop, that a stop will fill, or that an account is protected.

The pure function requires exactly one ACTIVE, reduce-only stop with the correct closing side, matching account/position/instrument/provider/venue, matching position revision, zero already-executed stop quantity, and exact remaining stop quantity equal to remaining open position quantity. Multiple stops, duplicates, partial executions, uncertain/cancelled status, stale observations, timestamp anomalies and mismatches fail closed. Snapshot age has a hard 3-second ceiling. Only a trusted server clock may be supplied in a future integration.

Declared cash loss uses exact Decimal arithmetic and the **worse** of the stop trigger and a separately declared adverse stress exit, plus declared costs. The stress input is mandatory; a zero/unavailable stress never passes. This is **not** a bound on gap/slippage or real maximum loss. Actual fills can be worse; FX conversion, financing, trading halts, broker margin rules, instrument multipliers, fees and execution venue are not authenticated.

The SHA-256 review fingerprint is an **unkeyed diagnostic digest**, not authentication, a signature, or evidence of an immutable audit trail. Do not include secrets in snapshots. All broker, paper-execution and reservation-release permissions remain false.

Run synthetic tests from `backend`: `PYTHONPATH=. pytest -q tests/test_paper_stop_coverage_review.py`.

## Integration handoff

Do **not** wire to an order sender. First reconcile authenticated broker positions, stop-order state and fills atomically with the paper journal and persistent risk reservations. Persist verified snapshot sequence/checkpoints and order identifiers, quarantine uncertain and duplicate acknowledgements, test concurrent PostgreSQL writers and process restarts, and verify production backup restore/rollback/health. Owner must explicitly confirm each live order with separately provisioned supported-provider credentials. The [Trading 212 Public API](https://docs.trading212.com/api) documents Invest/Stocks ISA, **not CFD execution**.
