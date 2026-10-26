# Declared split-entry CFD cash-ledger reconciliation (offline only)

This additive backend module supports a **caller-declared, split-entry** reporting-currency ledger, unlike the merged single `NET_CLOSE` posting audit. It re-runs the complete declared financing → partial-fill/spread/slippage/commission → point-in-time FX → per-position rounding pipeline and compares the hypothetical rounded net for **every** closed position with the sum of that position's declared ledger entries.

**This is not a brokerage adapter or authenticated statement importer.** A broker may book gross P&L, multiple commissions, financing debits/credits, FX conversion entries, reversals, and later corrections. The module accepts multiple rows per category but does **not** independently verify whether a category is correct or complete. The census is self-declared. It cannot prove that a fee was not omitted, even when all declared counts reconcile.

## Interface

`fingerprint_split_ledger_policy(manifest, fx_policy, fx_sha, rounding_sha, cutoff, policy)` binds the exact source/provider/venue/account, reporting currency, position open/close clocks, upstream policy digests, evaluation cutoff, and complete expected ledger-kind census.

Policy keys (exact):
- `max_posting_delay_seconds`: integer 0–2,592,000; latest permitted posting is close plus this delay.
- `max_receipt_lag_seconds`: integer 0–2,592,000; latest receipt lag after posting.
- `expected_receipts`: exactly one `{position_id, kind, count}` row per position **for each** of `PNL`, `COMMISSION`, `FINANCING`, `FX_CONVERSION`, `REVERSAL`. Zero counts must be explicit; `PNL` count must be at least one. Counts are 0–32, maximum 32 per position and 2,048 overall.

`audit_declared_split_cash_ledger(..., ledger_policy, expected_ledger_policy_sha256, ledger_events)` accepts at most 2,048 events. Each event must contain **exactly** `event_id, position_id, provider, venue, account_alias, currency, kind, posted_at, received_at, amount_cash, statement_sha256`. Cash is a signed exact decimal string at the caller-declared reporting minor-unit precision (0–6). Negative zero, exponents, excess precision, NaN and invalid IDs are rejected. A receipt ID must be globally unique.

Times are integer epoch seconds. Posting must occur after position open and no later than close plus policy delay; `PNL` and `REVERSAL` must post at or after close. Receipt must be at or after posting, within configured lag, and no later than the historical evaluation cutoff. This post-close PNL rule is a **modelling restriction**, not a universal broker rule. The audit rejects cross-source, cross-account and cross-currency events, unknown categories, extra receipts, duplicate IDs and invalid statement digests. Events are sorted before their deterministic declaration fingerprint is calculated; input order does not affect results.

## Fail-closed outputs

- `COMPLETE_SELF_DECLARED_ONLY`: all declared kind counts match and each position's sum equals the re-audited rounded hypothetical cash. A net total is returned, but it is **not verified broker cash**.
- `WITHHELD_INCOMPLETE_UPSTREAM`: financing, execution, FX or rounding is incomplete; no net is returned.
- `WITHHELD_INCOMPLETE_DECLARED_LEDGER`: missing declared event(s), with missing position/kind/count details; no net is returned.
- `MISMATCH_DECLARED_LEDGER`: exact per-position cash differences are shown; aggregate is withheld.
- Invalid, extra, duplicated, future or cross-source evidence raises `ValueError`.

The categories are descriptive and **not component-level proofs**: an overstated PNL entry could offset an understated financing entry and still reconcile. All timestamps and SHA-256 digests are caller supplied; they are not independently authenticated or externally timestamped. The model does not support cross-currency split postings, asynchronous post-cutoff settlements, partial statement imports, broker-specific reversals/settlement rounding, or audit of missing positions outside the supplied manifest.

The flags `source_authenticated`, `broker_settlement_verified`, `untouched_holdout_verified`, `verified_profitability`, and `may_execute_order` are always false. No market/provider calls, live/demo orders, persistence, licensed data publication or deployment changes are introduced.

Test command: `cd backend && PYTHONPATH=. pytest -q tests/test_declared_split_cash_ledger_audit.py`

End-to-end **synthetic** tests exercise split commissions, financing, fills, FX, rounding, missing fees, duplicate IDs, mismatches, source/clock restrictions, as-of financing revisions, and a deliberately offsetting component manipulation that demonstrates the remaining authenticity limitation.

## Next research

Before broker-realistic settlement verification, collect independently authenticated **read-only** statement exports with provider-specific event types, corrections, event IDs, currency and point-in-time availability, establish an external census, and reconcile each fee/financing/FX component separately. Keep this disconnected from all order execution and protect untouched holdouts.
