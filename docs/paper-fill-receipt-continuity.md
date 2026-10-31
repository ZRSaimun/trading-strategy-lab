# Loop 4 — disconnected paper fill receipt continuity review

`backend/app/paper_fill_receipt_guard.py` reviews **caller-supplied** cumulative fill snapshots. It never fetches broker data, places orders, releases risk reservations, changes protective stops, or writes to a database. It does not make a terminal state or fill receipt authentic. Its decision is **always** `HOLD_RECONCILIATION`, even when structural checks pass. This is intentional.

## Coverage

- Validates exact decimal-string quantities, prices, fees, and point values, with bounded sizes and decimal precision; rejects duplicate fill IDs, excessive fills, invalid timestamps, receipt latency, and quantities beyond the requested amount.
- Verifies `OPEN`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, and `REJECTED` status against cumulative quantities. Unknown state requires reconciliation. A canceled order may retain already-filled exposure; cancel acknowledgment is not proof of zero exposure.
- Compares an independently retained prior snapshot to the current snapshot: immutable order terms and prior fill receipts, advancing revision/time, monotonic cumulative quantity, no terminal-state regression, and no backdated newly discovered fills.
- Computes weighted average fill price, cumulative fees and an **illustrative** stop-based loss, including known fees. It checks declared caps but does **not** estimate current mark-to-market loss or guarantee a stop fill. Stops may gap; the actual loss can exceed the estimate.
- Emits a deterministic SHA-256 receipt-population fingerprint using hashed aliases; this fingerprint is **not** authentication, authorization, or tamper-proof storage.

## Integration restrictions

The caller must provide trusted, independently persisted prior observations, authenticated broker receipts, broker-sourced order state, and verified instrument point-value/currency metadata before any integration with the paper journal. Use transactionally consistent database updates and account-wide risk reservations; quarantine missing, altered, reordered, duplicated or uncertain receipts. A structurally valid result is **not** a green light to execute, retry, settle, or release reservations. Live brokerage needs separate provider support, secure credentials and positive owner confirmation for each individual order. Trading 212 public API does not document CFD order execution.

## Local tests

From `backend/`: `PYTHONPATH=. pytest -q tests/test_paper_fill_receipt_guard.py`. These are synthetic unit tests, not authenticated broker integration or PostgreSQL concurrency tests. No production deployment is authorized by this module.
