# Loop 2: declared confluence aggregate reconciliation (read-only)

This disconnected standard-library audit verifies **internal arithmetic only** in the 27 October 2026 exploratory 16-annual-archive, eight-state confluence table. The machine-readable JSON copies the *rounded* 0/5-bps means and state counts from `offline-sweep-32-archive-confluence-census-20261027.md`; the 0-bps overall mean (0.00731R) is reconstructed from those rounded cells, not an independently obtained market statistic. This is **not** a rerun of the 32 ZIP archives or of the committed Decimal trade engine, an authenticated source receipt, a broker fill, a confidence interval, an untouched holdout or a strategy-selection method.

From `backend/`:

```sh
PYTHONPATH=. python -m app.offline_sweep_aggregate_audit ../docs/offline-sweep-32-archive-confluence-aggregate-20261027.json
PYTHONPATH=. python -m pytest -q tests/test_offline_sweep_aggregate_audit.py
```

The audit fails closed if any of the eight fixed FVG/MSS-proxy/displacement states is missing or duplicated; state or total counts do not reconcile; empty observed cohorts have invented returns; reported observed-only means are nonfinite, inconsistently rounded or inconsistent with the weighted state means; or adding hypothetical 5-bps costs improves a cell's return. It refuses any declaration of independent holdout, verified profitability or order permission. A 0.00001R tolerance accommodates two layers of five-decimal-place rounding, **not** an arbitrary discrepancy in unrounded trade records.

The sole positive observed +5-bps cell has **six trades**. Its descriptive positive mean does not validate a candidate or support paper/live activation: it was discovered among already-inspected states and other diagnostics. All **244 annual later-slice censored entered exits** remain unknown and un-imputed. The full observed annual later-slice mean is about **−0.30760R** at hypothetical additional 5 bps. Executable spread, slippage, financing, quote-side, timezone, source rights and protected prospective evidence remain unavailable.

This code is not imported by any production API, database, signal filter, order route, or deployment process. No raw archive, credentials, hashes or proprietary candle data are published. Keep PR #136 draft/unmerged/undeployed until production restore, rollback, health and owner-confirmed hosting safeguards are independently verified. Real-money orders always require supported scoped account, fresh executable quote, hard risk checks and explicit per-order owner confirmation.

## Strict JSON input hygiene (additive)

The three offline aggregate command-line auditors (reconciliation, censored-exit net-R tipping and observed-only 0–5bps cost crossing) now share a bounded strict JSON loader. It reads at most 4,000,001 bytes, rejects reports larger than 4,000,000 bytes, rejects duplicate keys at **any nesting depth** (including overwritten provenance/permission fields and state counts), and rejects nonstandard `NaN`/`Infinity` tokens. The validator still reconciles the declared report after parsing. This prevents silent last-key-wins interpretation of conflicting JSON claims; it does **not** authenticate source archives, establish actual broker execution costs, fill unknown exits, create an independent holdout or demonstrate profitability. No strategy admission, production path, broker interface or order permission is changed.

Synthetic CLI regressions: `PYTHONPATH=. pytest -q tests/test_offline_sweep_aggregate_json_input.py` from `backend/`.

## Frozen closed-schema enforcement (28 October 2026)

The aggregate arithmetic auditor now rejects **unknown or missing keys** at the
report, individual eight-state row, and totals levels. The existing fixed 0/5
basis-point mean maps already require exactly those two keys. This prevents a
caller from attaching misleading undeclared assertions such as
`broker_verified_or_selected: true` while obtaining a successful arithmetic
audit. All three offline aggregate CLIs inherit the check because both derived
auditors first invoke `audit_aggregate`.

The committed 27 October aggregate JSON remains valid without modification.
This is a deliberately **closed schema** for one already-inspected exploratory
report, not a generic extensible market-data format. Any future legitimate
metadata requires an explicitly reviewed schema version and corresponding
tests; do not silently accept extra provenance or execution fields. The check
does not cryptographically authenticate the report or verify source rights,
BID/ASK fills, cost receipts, independent holdout, missing exits or profits.

Synthetic regression command (from `backend/`):
`PYTHONPATH=. python -m pytest -q tests/test_offline_sweep_aggregate_closed_schema.py`.
No original archives are read, no trading decisions are changed and no
production or broker path imports this offline auditor.
