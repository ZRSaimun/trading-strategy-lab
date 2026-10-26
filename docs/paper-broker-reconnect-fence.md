# Paper broker reconnect quarantine (Loop 4)

`backend/app/paper_broker_reconnect_fence.py` exports
`evaluate_paper_reconnect(before, after, *, disconnect_at_ms,
reconnected_at_ms, now_ms, ...)`.

**Purpose:** prevent a disconnected or stale paper broker session from being
mistaken for a reconciled, safe-to-trade session. The function is disconnected,
read-only and uses **caller-declared** evidence. It never contacts a broker,
submits an order, changes a reservation or grants approval. Every result is
`HOLD_RECONCILIATION`, including structurally clean snapshots.

## Reconnection safety checks

- Same broker/account/feed; a single monotonic connection-epoch increment;
  increasing snapshot and quote sequence; monotonic order and fill sequences.
- Chronologically possible disconnect, reconnect, inventory and quote receipt
  timestamps; post-reconnect inventory and quote observations; bounded quote
  age, transport lag and snapshot age.
- Prior working orders remain working or have a declared terminal receipt;
  no silent disappearance, unexplained new working order, duplicate IDs,
  or ambiguous order outcomes. A filled terminal receipt requires a higher
  fill sequence; a higher fill sequence without a declared fill is flagged.
- Risk revision changes during the outage require reconciliation. A prior
  unknown outcome remains quarantined even if it disappears from the later
  snapshot.
- Strict bounded schemas and identifier populations; no booleans accepted as
  counters; deterministic SHA-256 diagnostics (not a signature).

The evaluator intentionally **does not** infer that any terminal receipt,
quote, account inventory, protective stop, OCO linkage, or account balance is
broker-authenticated. Nor does it infer cancellation from a missing order.
Actual broker reconnect readiness requires authenticated, provider-specific,
durably persisted account snapshots and full open/pending/unknown order and
fill reconciliation; verified protective-stop acknowledgements; a persistent
risk kill switch; fresh server-owned policy and quote validation; and a fresh
human-approved, one-order preview. Any uncertain order must remain quarantined
without blind resubmission. A broker can fill an order during a disconnect.

The caller must supply a trusted server clock. These checks cannot detect
a malicious caller fabricating timestamps or revisions. They are not a
brokerage order admission gate, not a production safety certification, and
not a maximum-loss guarantee.

## Synthetic tests

`cd backend && PYTHONPATH=. pytest -q tests/test_paper_broker_reconnect_fence.py`

The suite covers reconnect chronology, stale quote reuse, source/account
switches, working/terminal order populations, unknown outcomes, fill sequence,
strict input validation and deterministic fingerprints.

## Brokerage compatibility

As checked on 26 October 2026, the official Trading 212 Public API
documentation supports Invest and Stocks ISA accounts (demo and live), **not
Trading 212 CFDs**: https://docs.trading212.com/api

No provider credentials, API connection, order execution, paid services,
data migrations, or production writes are introduced by this change.
