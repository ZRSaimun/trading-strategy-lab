# Offline M1 archive-level robustness stress (research only)

`app.offline_m1_archive_robustness.audit_m1_archive_robustness(reports)` accepts 2–64 **original self-hashed v1 receipts**, first validating the existing source-isolated `audit_m1_multi_archive_census`. It does not read or publish ZIP archives, prices, or account data. It does not execute trades or call external services.

For each instrument/provider and each **illustrative** 0/5/10/20 bps round-trip cost, the audit computes the trade-count-weighted mean, equal-archive mean, worst/best archive mean, number of archive means positive after cost, and minimum/maximum trade-weighted means after deleting **one entire archive**. All means use six-decimal rounded source receipts and are therefore approximate. Archive SHA-256 identities are sorted before hashing the result, so input order does not alter the fingerprint. Duplicate archives/manifests and forged research fingerprints fail closed via the existing census. Empty archives never count as successful observations; single nonempty archive groups cannot produce a deletion stress. Counts greater than 500,000 or original bar count, and absurd gross means above 1,000,000 bps, are rejected.

**This is not an inferential confidence interval or a chronological out-of-sample test.** Archive observations may share market regimes, source errors and date overlap; treating individual trades as IID would understate uncertainty. The source receipt has no authenticated archive date range, so hash ordering must never be mistaken for chronological ordering. The 32 owner-provided archives already explored in the adjacent methodology document are **not** protected holdouts, and this new module has only synthetic regression verification unless original v1 receipts are separately supplied. A positive stress statistic would not prove a profitable strategy.

Run offline synthetic tests:

```sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_archive_robustness.py
```

The return flags always deny trading, verified profitability, authenticated source, executable quotes, statistical significance and protected holdout. This is a research-only feature; it must not be exposed as a live BUY/SELL signal. Before strategy promotion, obtain independently authenticated archive metadata and fresh untouched chronological data, then evaluate source-specific executable BID/ASK, spread, commission, slippage and financing assumptions without tuning on the holdout.

## 29 October 2026 — incomplete-source stress quarantine

For a source cohort containing any zero-outcome original archive, **all** cost-scenario return metrics, positive-archive counts, and leave-one-archive-out extrema are now null. The result retains `INCOMPLETE_ARCHIVE_COVERAGE`, archive identities and population counters for diagnostics. The prior behavior could display a favorable mean from only the remaining nonempty archives, even though the source cohort was incomplete. A complete cohort of another instrument/provider is not suppressed. This is a fail-closed reporting correction, not new market evidence or a trading signal.
