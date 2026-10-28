# Read-only UNKNOWN ledger and broker inventory bridge

This additive diagnostic compares the **caller-declared** output of
`app.paper_submission_attempt_ledger.inspect_ledger` (from draft PR #148)
with the **caller-declared** expected UNKNOWN order population and the
snapshot/context-anchor audit in draft PR #152. The ledger implementation
is **not imported**: these PRs are independent and not integrated in the
deployed application.

Use `inspect_declared_ledger_inventory_bridge(expected, snapshots,
check_times_ms, prior_snapshot_digests, prior_chain_digest,
prior_context_digest, ledger_summary, prior_ledger_tip_sha256,
max_checkpoint_gap_ms=60000)`.

The bridge requires an exact v1 ledger-summary shape, consistent event/order
counts, a nonzero SHA-256 ledger audit tip, an independently *previously
retained* matching tip, and exact agreement between the target account's
`ATTEMPT_UNKNOWN` order IDs and the census expected IDs. It preserves
all failures from the full census, replay, snapshot-anchor and context-anchor
audits. An extra UNKNOWN order, missing UNKNOWN, mutated ledger tip, unsafe
execution claim or invalid schema fails closed.

**Important limitations:** This check compares identifiers, **not intent
fingerprints**. The current ledger summary omits intent SHA values; do not
infer intent binding from a matching ID. Caller-provided ledger summaries,
snapshots, clocks and hashes are not authenticated, and a locally computed
SHA-256 tip is not an independent immutable custody record. A compromised
caller can fabricate matching evidence. The bridge never reads SQLite,
contacts a broker, reconciles or releases an UNKNOWN submission, places
paper/live orders, reserves risk, or modifies production data.

A clean diagnostic remains
`DECLARED_LEDGER_INVENTORY_CANDIDATE_UNVERIFIED`. All execution,
broker-authentication, ledger-authentication and quarantine-release flags
remain **false**.

## Testing and release gate

Synthetic regression suite:
`cd backend && PYTHONPATH=. python -m pytest -q tests/test_paper_broker_ledger_inventory_bridge.py`.

Do not merge or deploy based solely on synthetic tests. Before any future
execution integration, obtain provider-authenticated read-only order/fill
receipts, immutable externally controlled ledger/snapshot anchors, a trusted
intent-SHA projection, atomic nonce and risk reservations, verified stops,
fresh executable quotes, and explicit owner confirmation for each live order.
Require complete exact-head CI, independent backup restoration, rollback
rehearsal and authenticated production health checks.
