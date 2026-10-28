# Declared broker reconciliation context anchor (offline, no execution)

Snapshot/chain hashes alone **do not bind** the expected unresolved order intent fingerprints, attempt timestamps, freshness/transport policy, caller-declared trusted checkpoint times, or maximum permitted observation/checkpoint gap. A previously retained snapshot anchor can still match after those separate inputs change.

The additive module `app.paper_broker_reconciliation_context_anchor` closes this **diagnostic** gap. `fingerprint_declared_reconciliation_context(expected, check_times_ms, max_checkpoint_gap_ms=60000)` deterministically hashes a versioned, canonical JSON representation of all three inputs with a domain-separated SHA-256 digest. The helper rejects malformed clock populations, non-increasing clocks, invalid gap policy, non-JSON inputs and oversized contexts. It does **not** independently validate broker records or trusted clocks.

`inspect_declared_reconciliation_context_anchors(expected, snapshots, check_times_ms, prior_snapshot_digests, prior_chain_digest, prior_context_digest, max_checkpoint_gap_ms=60000)` first runs the full existing inventory census, replay chain and snapshot-anchor audit. It then compares the exact context digest against a caller-provided prior digest. Any changed context yields `HOLD_RECONCILIATION` and `reconciliation_context_digest_mismatch`; underlying replay or snapshot failures are preserved. Invalid digests and schemas raise `ValueError`.

**Custody and security:** All inputs and anchors are caller-declared and unauthenticated. Record all three anchor types (per-snapshot, ordered chain, and context) in independently controlled immutable custody *before* evidence can be modified. Matching hashes are **not** broker signatures, account ownership proof, completeness proof, order authorization, or release of `ATTEMPT_UNKNOWN`. All `may_clear_unknown`, `may_submit_paper_order`, and `may_submit_real_order` flags remain false. There is no network access, database write, provider integration, or execution path.

Test: `cd backend && pytest -q tests/test_paper_broker_reconciliation_context_anchor.py`. Synthetic fixtures only; no real broker acceptance.
