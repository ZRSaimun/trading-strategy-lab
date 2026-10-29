# Declared receipt ↔ session-gap reconciliation (offline only)

`app.declared_m1_receipt_gap_reconciliation.audit_declared_m1_receipt_gap_reconciliation`
combines the existing prospective completed-M1 receipt census with the
session-aware missing-minute gap audit. It is an **opt-in, pure, read-only**
consistency check: no network, credentials, storage, vendor access, calendar
downloads, historical repair, broker access, alerts, or orders.

The caller supplies an immutable `ExpectedM1Manifest` with explicit UTC
sessions and exclusions plus a bounded list of completed-bar receipts with
exact source identity and OHLC. The receipt census validates receipt schema,
chronology, OHLC and declared freshness; the gap audit separately checks
duplicates, backward candle-start transitions, session boundaries, declared
closures, missing runs and trailing expected-minute coverage. The wrapper
requires exact agreement between the two algorithms on the manifest digest,
expected population, missing population, unexpected population, duplicate rows
and unique observed population. A disagreement raises `ValueError`, not a
best-effort partial report.

A fully consistent result is `DECLARED_RECONCILED_UNVERIFIED`, **not**
authenticated, licensed, fresh, executable, or approved for forecasting.
A stale/late receipt, missing candle, duplicate, unexpected candle, backward
bar-start transition **or backward declared receipt-time transition** yields
`REVIEW_REQUIRED`. In particular, out-of-order backfills may pass the original
receipt census's timestamp-set completeness check but are flagged by this
combined audit. Receipt-time reversals are counted across adjacent input rows,
with up to `sample_limit` timestamp-only samples; equal receipt timestamps are
allowed, and `sample_limit=0` suppresses samples without suppressing counts.
The caller must preserve its original receipt input order: sorting by bar start
or receipt time before this audit would destroy ordering evidence. A reversal
is an offline review signal, not proof of clock tampering; the declared
`received_at_utc` values are **not** server-attested timestamps. Both underlying reports remain
available under `receipt_census` and `session_gap_audit`; they expose no raw
OHLC prices. Fingerprints are local reproducibility hashes, not signatures.

All results explicitly keep `independent_calendar_verified`,
`source_authenticated`, `provider_entitlement_verified`,
`server_receipt_clock_attested`, `executable_bid_ask_verified`, `live`,
`forecast_ready` and `may_execute_order` false. A declared UTC calendar is
not an independently verified session/DST/holiday source; a caller-declared
receipt timestamp is not a trusted server receipt. The function does not
authorize changing a forecast or trading state.

Synthetic test command:

```sh
cd backend && PYTHONPATH=. pytest -q tests/test_declared_m1_receipt_gap_reconciliation.py
```

Activation still requires authenticated licensed provider observations,
independent venue calendar and UTC/DST provenance, server-owned durable
receipt timestamps, executable BID/ASK lineage when applicable, independent
staging, backup restore, rollback and authenticated production health checks.
The large draft PR must not be merged merely because this offline audit passes.
