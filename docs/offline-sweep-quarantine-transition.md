# Paired source-local causal quarantine transition audit

This disconnected, read-only research function compares **the exact same original complete M15 bars** under two alternative caller-declared duplicate-M1 timestamp inventories. It identifies which structurally eligible *candidate confirmation windows* become duplicate-touched or clean when a declaration changes. This is a **matched candidate denominator** analysis, not a matched-trade effect, signal backtest, source authentication, UTC mapping, or profitability result.

```python
from app.offline_sweep_quarantine_transition import audit_quarantine_transition

report = audit_quarantine_transition(
    original_source_local_m15_bars,
    baseline_duplicate_m1_times, revised_duplicate_m1_times,
    dataset_id=dataset_sha256, archive_sha256=original_zip_sha256,
)
```

Both inventories must be sorted unique source-local ISO timestamps with no timezone suffix. Both are independently checked by the existing frozen quarantine auditor. The comparison keeps the original 70/30 index split, 16-bar embargo, 16 prior completed M15 candles, sweep and completed confirmation fixed. The function counts all candidate indices in development and exploratory-later separately, regardless of whether a strategy signal or entered trade exists. A 3×3 matrix gives baseline class by revised class: `gap_or_segment`, `declared_duplicate_touched`, `quarantine_clean`. Every row/column must reconcile to independently computed class counts; source gap windows must not change class merely because duplicate declarations change. New and removed duplicate declarations are not assumed authentic.

The output includes `gained_clean_causal_windows`, `lost_clean_causal_windows`, `unchanged_clean_causal_windows`, and deterministic domain-separated hashes of changed candidate indices and source-local sweep/confirmation timestamps. Raw timestamps and OHLC values are not included in the report. These unsalted SHA-256 hashes are reproducibility fingerprints, **not source authentication, signatures or secrecy protection**. Keep reports derived from licensed data private.

**No lookahead:** the structural classification uses only the 18 candles available at the completed confirmation. Future entry and exit bars, stop/target outcomes and costs cannot change a candidate's class. It does not filter signals by retrospective observability. A changed structural denominator must not be interpreted as a change in trading expectancy or an improvement in model performance. The original archive clock and source-to-UTC mapping must be independently verified before cross-workstream comparisons; the already-inspected later period is not a protected holdout. Executable BID/ASK, spreads, commissions, slippage and financing remain unverified.

Tests are fully synthetic (`PYTHONPATH=. pytest -q tests/test_offline_sweep_quarantine_transition.py` from `backend`). No provider calls, paper/live orders, production database writes, deploys or paid services are performed. Release remains blocked pending independent restore/rollback/health and hosting ownership checks.
