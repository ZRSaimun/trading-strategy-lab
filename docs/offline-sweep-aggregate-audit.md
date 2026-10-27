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
