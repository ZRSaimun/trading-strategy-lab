# PAPER inventory continuity audit (Loop 4)

This disconnected, **read-only** guard compares two caller-declared paper account risk snapshots. It re-runs the merged `paper_account_exposure_guard` on both snapshots using separate, caller-supplied clock readings, then refuses to treat changes as safe without independent broker evidence. The API is a Python function only; there is **no HTTP endpoint, broker SDK, credential storage, database migration, order sender, or risk-budget release**.

`audit_paper_inventory_continuity(previous, current, previous_now_ms=..., now_ms=...)` requires strictly increasing integer clock readings. A gap over 60 seconds causes `HOLD_RECONCILIATION`. Existing order IDs must remain present, no new unreserved order IDs may appear, and risk terms, state, account alias, currency, caps, equity and daily realized P&L must not silently change. Quote observation and receipt clocks must advance for each surviving order. Replayed quotes, an emergency-latch clear, a breached stop or a failed underlying risk check cause a hold. Legitimate fills, cancels, broker fee settlements and policy updates will also hold until a future independently authenticated reconciliation protocol exists.

The result reports aggregate change counts and a deterministic diagnostic SHA-256, never raw order IDs or tokens. The digest is **not** a signature, proof of completeness, authenticated owner approval, or execution permission. Every result returns `may_execute_paper_order: false` and `may_execute_real_order: false`, even when the declared snapshots are internally consistent.

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_paper_inventory_continuity.py
```

## Safety and integration handoff

This conservative continuity gate does **not** prove that an unchanged snapshot is complete, that quotes are authentic, that stops are placed, or that fills and cash balances reconcile to a broker. An attacker or a broken upstream source could omit an order from both snapshots. The caller must supply authenticated, complete broker inventories, durable source/sequence markers and verified terminal receipts. Do not use this function as a standalone order authorization gate or release risk on a reported disappearance. Integrate atomically with durable paper reservations (draft PR #26), quote/journal checkpointing, duplicate-order quarantine, daily-loss latches, and broker snapshot reconciliation. Add disposable PostgreSQL concurrent-writer and crash-recovery acceptance before enabling any paper lifecycle transitions.

Trading 212's documented public API covers Invest and Stocks ISA, including demo access, but **not CFD order execution**. No provider is connected by this change. Real-money execution requires a separately supported broker, secure credentials and positive human confirmation for **each specific order**. There is no profitability evidence. Do not merge/deploy until exact-head CI, latest-main conflict review, and independently verified backup, rollback and health checks are complete.
