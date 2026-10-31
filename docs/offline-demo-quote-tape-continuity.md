# Offline demo quote-tape as-of continuity (Loop 3)

`app.offline_demo_quote_tape_continuity.audit_declared_demo_quote_tape_continuity` is an **opt-in, read-only** comparison of two caller-declared, disconnected demo quote-tape scenarios. It imports the existing quote-tape simulator, revalidates both snapshots and recomputes both hypothetical results; it never submits an order or authorizes trading.

## What it checks

- The later evaluation cutoff strictly advances, while provider, venue, account alias, instrument, currency, spread/freshness/slippage/commission policy, and order intent remain unchanged.
- A cancellation first disclosed in the later view must have been requested **strictly after** the earlier evaluation cutoff; an existing cancellation cannot be changed or erased.
- The earlier quote population must remain an **exact prefix** of the later population. Newly appended quotes must have `received_at_ms` strictly greater than the earlier cutoff. A quote observed earlier but received later is allowed; no receipt is made available retroactively.
- Each tape must match its supplied SHA-256 fingerprint. Earlier hypothetical fills must remain an exact prefix of later fills, and total hypothetical quantities and entry-side costs cannot decrease.
- Both `may_execute_demo_order` and `may_execute_real_order` are always `false`. The output distinguishes earlier/later hypothetical quantities, newly declared hypothetical fills, and unauthenticated evidence flags.

## Scope and limitations

The audit does **not** prove either tape was independently captured at its stated time. A caller controlling both tapes can consistently omit, invent or rewrite history before submitting both. SHA-256 digests here are unsigned, self-declared fingerprints, not broker attestations. The audit does not verify actual order fills, queue priority, order-book depth, broker event completeness, real spreads/slippage, financing, FX settlement, fees beyond the declared entry-side commission, market halts or multi-year profitability. It does not create a persistent record or a broker adapter. It only prevents *inconsistent declared* as-of snapshots from silently passing.

Synthetic verification: from `backend/`, run `PYTHONPATH=. python -m pytest -q tests/test_offline_demo_quote_tape_continuity.py`. For independent assurance, capture immutable provider-authenticated quotes and broker receipts outside the application, and run protected chronological walk-forward/holdout evaluation net of all real trading costs. Do not treat any passing scenario as proof of a profitable edge or permission to place demo/live orders. No Trading 212 CFD API is assumed.

Release: additively isolated library + tests + documentation only. Do not merge or deploy until exact-head full CI, changed-file overlap review, and the independently verified production backup, rollback and health gates have passed. No licensed archives or credentials are included.
