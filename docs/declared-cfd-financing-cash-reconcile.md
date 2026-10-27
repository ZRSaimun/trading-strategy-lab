# Offline declared CFD financing-to-cash reconciliation

`backend/app/declared_cfd_financing_cash_reconcile.py` is a **pure, read-only, fail-closed** research preflight. It does not connect to a broker, authenticate a statement, store data, place demo/real orders, verify returns, or claim profitability.

## Contract

Call `audit_declared_financing_cash(scope, due_rollovers, events, cash_postings)` only after independently preserving original broker statements and reconciling a separate broker-specific rollover calendar. `due_rollovers` must be the **full, chronological, position-bounded** due-rollover population, ideally the `declared_due_rollovers` field from the separately validated calendar audit. The `scope.calendar_sha256` should match that calendar's returned fingerprint. **Neither string matching nor self-declared hashes prove provenance**. Source identifiers must be tied to original retained evidence by a separate authenticated process.

All dictionaries have exact schemas (see module constants). Epoch timestamps are integer UTC seconds; amounts are signed decimal **strings** in the declared settlement currency, with negative cash debits and positive credits. For every due rollover, exactly one financing event and exactly one matching cash posting are required. Cash posting references its financing event ID and must match the exact amount, account, position and currency. Event booking and posting may be after position close but must not be after `as_of_utc`. Duplicates, missing/extra events, inconsistent chronology, altered receipts, cross-account/position/instrument entries, floats and non-finite amounts are rejected.

Example, **invented and not actual brokerage evidence**: `-1.25`, `+0.75`, `-0.50` are entered as `"-1.25"`, `"0.75"`, `"-0.50"`. They reconcile to a net cash delta of `-1.00` and a declared financing cost of `1.00` in the settlement currency.

## Limits and release safety

This intentionally supports **one event and one posting per due rollover**; brokers may split charges, net across positions, post delayed adjustments, charge different settlement currencies, or apply tax, conversion, rebates and holiday exceptions. Those require provider-native event mapping, explicit correction handling, immutable statement provenance and FX settlement reconciliation, not silently coercing these records into this model. A missing posting is an error, not a zero-cost assumption. Zero-value financing events are rejected until a separate explicit broker-waiver evidence model exists. Zero due rollovers is not proof of free financing. The digest is unsigned and can be recomputed by a caller.

Real historical costs are not available at strategy entry time merely because they can be reconciled retrospectively. Never feed realized financing/cash outcomes into development features, walk-forward candidate selection, or untouched holdouts. No broker source, rates, FX conversion, executable quotes, trading edge or account eligibility is established. Both demo and real-order permissions remain false. This code is safe to test offline and must not be wired to an execution route without separate review.

Synthetic regression tests: `cd backend && python -m pytest -q tests/test_declared_cfd_financing_cash_reconcile.py`.
