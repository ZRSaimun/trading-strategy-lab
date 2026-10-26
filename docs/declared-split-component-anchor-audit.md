# Declared split-ledger component anchors — offline only

`backend/app/declared_split_component_anchor_audit.py` adds a **separate caller-declared per-position/per-kind reference** on top of the existing split cash ledger audit. It catches one weakness of net-only reconciliation: an overstated PNL entry can offset an understated financing entry without changing the position's total. This audit withholds reconciled cash when category-level disagreement is present.

The reference is **not authenticated**. A caller can rewrite anchors and recompute SHA-256. This check cannot detect two offsetting incorrect entries *within the same category*, missing positions outside the manifest, forged statement hashes, incorrect broker mappings, or tampering with both reference and events. It does not prove independent ledger provenance, economic profitability, or suitability for real trading.

## Interface

`fingerprint_split_component_policy(manifest, ledger_policy, ledger_sha, cutoff, component_policy)` returns a deterministic SHA-256 of the complete reference declaration, source identity, cutoff and upstream ledger-policy SHA. The reference policy requires **exactly**:

- `reporting_currency`: uppercase three-letter currency matching the FX policy.
- `reporting_minor_units`: integer 0–6 matching the rounding policy.
- `reference_statement_sha256`: a caller-declared 64-character lowercase hexadecimal statement hash, **not verified against a file**.
- `reference_captured_at`: integer epoch seconds not later than the evaluation cutoff; self-declared, not trusted proof of historical availability.
- `expected_components`: exactly one `{position_id, kind, amount_cash}` for every position and each of `PNL`, `COMMISSION`, `FINANCING`, `FX_CONVERSION`, `REVERSAL`. Include explicit zero amounts for zero-count categories. Signed decimal cash must respect reporting minor units, with no negative zero, exponent or NaN.

`audit_declared_split_component_anchors(...)` takes all upstream split-ledger arguments plus `component_policy` and `expected_component_policy_sha256`. It first recomputes financing, execution costs, as-of FX, rounding and split-ledger net, including the expected event-kind census. If upstream is incomplete or inconsistent, the component audit withholds all aggregate cash. Otherwise, it compares each category's exact sum of declared events to its separately declared anchor, reporting per-position/per-kind discrepancies. All comparisons use exact `Decimal` arithmetic.

- `COMPLETE_SELF_DECLARED_COMPONENTS_ONLY`: every declared category matches its declared reference, and the upstream position net matches. **Not authenticated broker settlement.**
- `MISMATCH_DECLARED_COMPONENTS`: one or more category sums differ; no aggregate is returned, even if offsetting changes preserve the net.
- `WITHHELD_UPSTREAM_*`: financing, execution, FX, rounding or split-ledger population did not reconcile; no aggregate is returned.
- Malformed, cross-scope, stale or inconsistent inputs raise `ValueError`.

All responses explicitly set `source_authenticated`, `broker_settlement_verified`, `untouched_holdout_verified`, `verified_profitability`, and `may_execute_order` to `false`. No network access, persistence, demo/live orders, credentials, licensed archives or deployment changes are added.

Run synthetic regressions with `cd backend && PYTHONPATH=. pytest -q tests/test_declared_split_component_anchor_audit.py`. The deliberately offsetting PNL/financing fixture now withholds the aggregate; a same-kind offset fixture demonstrates the remaining limitation.

**Next research:** Obtain authenticated, read-only broker exports with an independently sourced event/position census, stable event IDs, actual fee/financing semantics, and broker-specific correction/reversal rules. Only then compare component anchors to independently verified records. Keep untouched holdouts sealed and paper execution gated separately.
