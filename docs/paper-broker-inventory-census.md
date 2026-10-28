# Disconnected broker-order inventory census (Loop 4)

`backend/app/paper_broker_inventory_census.py` compares a caller-declared,
normalized, complete broker/account order snapshot against a bounded list of
submission attempts previously recorded as `ATTEMPT_UNKNOWN`.

This is **not a broker connector**. Inputs, page-completeness declarations,
provider order IDs and fill IDs are unauthenticated; a matching report cannot
prove that the broker accepted, rejected, cancelled or filled anything.
`DECLARED_TERMINAL_CANDIDATE_UNVERIFIED` means only that the supplied records
are internally consistent. **Never** use this result to clear quarantine,
retry a non-idempotent POST, or authorize a paper/live order. All six
execution/authentication/release flags are always false.

## Evidence contract

- `expected`: exact fields `broker`, `account_alias`, `max_snapshot_age_ms`,
  `max_transport_lag_ms`, `unresolved_orders`. Each unresolved order supplies
  `client_order_id`, `intent_sha`, `instrument`, `side` (`BUY`/`SELL`),
  positive decimal-string `quantity`, and `attempted_at_ms`.
- `observed`: exact fields `broker`, `account_alias`, `snapshot_id`,
  `sequence`, `observed_at_ms`, `received_at_ms`, `pages`. Every page supplies
  `snapshot_id`, zero-based `index`, `total_pages`, literal `complete: true`,
  and `orders`. Each order supplies `client_order_id`, `broker_order_id`,
  `instrument`, `side`, `quantity`, `status`, `filled_quantity`, and `fills`.
  Every fill supplies `fill_id`, positive decimal-string `quantity`, and
  `filled_at_ms`.
- `now_ms` must be supplied by a trusted caller clock, not an untrusted
  provider response. Timestamps are UTC epoch milliseconds.
- Strict schemas and numeric bounds: 1–256 unresolved orders, 1–16 pages,
  at most 256 observed order rows **across all pages** (including duplicates),
  at most 256 orders per page, at most 2,048 fills total, positive age/lag
  limits at most 60 seconds, finite decimal strings (16 integral and 8
  fractional digits maximum). Malformed inputs raise `ValueError`.
- Semantic mismatches fail to `HOLD_RECONCILIATION`: stale/future snapshots,
  transport delay, incomplete/misnumbered pages, unexpected/missing orders,
  duplicate order/fill identities, intent identity/quantity mismatch, fill
  totals, impossible status/quantity combinations and fill timestamps outside
  the attempt/snapshot window. Open and partial orders remain unresolved.

## Safety boundaries and next integration

The ledger in PR #148 uses durable SQLite quarantine; this isolated census
neither reads nor modifies it. The broker adapter must independently prove
account identity, immutable provider receipt provenance, complete paginated
order/fill inventory at one consistent snapshot, a trusted time source,
source-original retention, and an external audit anchor. Partial fills,
reversals, netting, order amendments, fees, cancellations after partial fills,
corrections and broker pagination races require separate provider-specific
handling. Never infer CFD API support from an equity API.

Next: integrate with atomic persistent risk reservations, verified protective
stops, stale-quote/reconnect controls, and individual signed human approval;
only after authenticated provider evidence and separate risk review may any
specific live order be considered. No profit claim, broker calls, credentials,
paid services, production migration or trading permissions are introduced.
