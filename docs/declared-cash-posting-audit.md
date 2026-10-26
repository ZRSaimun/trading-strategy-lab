# Declared cash posting reconciliation (offline research only)

This additive module (backend/app/declared_cash_posting_audit.py) re-runs the
merged financing → partial-fill/spread/slippage/commission → point-in-time FX →
hypothetical rounding pipeline. It compares the resulting **one net cash
amount per closed position** with caller-declared NET_CLOSE cash postings.

**Scope is deliberately narrow:** one reporting-currency net posting per
closed position. Brokers may instead post gross P&L, fees, financing, FX
conversion, and reversals as separate ledger entries. Those statement layouts
are **not** supported by this audit; do not coerce or silently aggregate them
into the NET_CLOSE schema. A matching amount is not broker verification.

## Interface

Freeze an explicit declaration policy with the function
fingerprint_cash_posting_policy(manifest, fx_policy, fx_sha, rounding_sha,
cutoff, posting_policy). The policy has max_posting_delay_seconds and
max_receipt_lag_seconds (each integer 0–2,592,000). The digest binds broker
provider/venue/account, reporting currency, the closed-position population
and close anchors, upstream FX and rounding policy digests, and the
historical cutoff. It is **not** an externally signed timestamp or evidence
of preregistration.

Call audit_declared_cash_postings(...) with the same upstream inputs plus
the policy, expected policy digest and a bounded list of postings. Every
posting requires exactly these fields:

- receipt_id, position_id, provider, venue, account_alias, currency, kind
  (must equal NET_CLOSE), posted_at, received_at, amount_cash,
  statement_sha256.

All times are integer epoch seconds. Postings must be at or after position
close, received by the evaluation cutoff, and satisfy both configured delays.
Amounts are decimal strings with no more fractional digits than the
**caller-declared** reporting minor units. The audit rejects duplicate
receipt IDs, extra positions, cross-source records, invalid timestamps,
wrong currencies and malformed hashes. Receipt order does not affect its
deterministic declaration fingerprint.

## Results and fail-closed semantics

- COMPLETE_SELF_DECLARED_ONLY: exactly one declared posting for each
  position and every amount equals the recomputed hypothetical rounded net.
- WITHHELD_INCOMPLETE_UPSTREAM: financing, fills, FX or rounding incomplete;
  no posted cash total is released.
- WITHHELD_INCOMPLETE_DECLARED_POSTINGS: at least one position lacks a
  posting; report missing IDs but no cash total.
- MISMATCH_DECLARED_POSTINGS: report each per-position signed difference,
  but **withhold** the aggregate reconciliation.
- Malformed, inconsistent, extra or duplicate evidence raises ValueError.

No status proves the declared receipts came from a broker, that the broker
uses the hypothetical rounding convention, that the archive was licensed,
that the holdout was untouched, or that any strategy is profitable.
broker_settlement_verified, source_authenticated, untouched_holdout_verified,
verified_profitability and may_execute_order are always false. No API calls,
real/demo orders, database mutations or licensed data are involved.

Test command: cd backend && pytest -q tests/test_declared_cash_posting_audit.py

End-to-end synthetic fixtures exercise partial fills, financing revisions,
point-in-time FX and exact-decimal posting reconciliation. For real broker
verification, independently authenticate statements, model the broker's
actual per-ledger-entry postings and FX/fee/rounding conventions, and retain
unmodified receipt provenance. Never use a matching declared hash as proof.
