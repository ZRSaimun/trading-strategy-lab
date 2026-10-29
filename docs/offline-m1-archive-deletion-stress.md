# Whole-archive deletion stress (offline research only)

`app.offline_m1_archive_deletion_stress.audit_m1_archive_deletion_stress(reports)` takes 2–64 original v1 M1 research receipts. It first runs the existing source-isolated archive robustness and census validation. Receipts must have intact self-hashes and consistent original exploratory populations. Self-hashes **do not** authenticate provider data or licensing.

For each instrument/provider separately, remove every possible combination of 1, 2, or 3 **entire archives**, retaining at least one. Compute the exact minimum and maximum trade-count-weighted gross return of the remaining archives, then subtract illustrative 0, 5, 10, and 20 bps round-trip costs. The audit reports how many deletion combinations were evaluated and minimum/maximum remaining outcome populations. With at most 64 original receipts, there are at most 41,664 three-archive combinations. Calculations use decimal arithmetic and six-decimal output rounding; archive identity ordering is deterministic but **not chronological**.

A source group with **any empty archive** withholds all deletion extrema rather than quietly selecting only the favorable observed archives. If the group has too few archives to remove k while retaining one, that k's statistics are null. The output binds to the preceding robustness receipt fingerprint and always denies trading, source authentication, statistical significance, executable quotes, verified profitability, and protected holdout.

These extrema are **not** confidence intervals, probability estimates, broker-executable backtests, or evidence of a profitable edge. Archive dates, independence, time zones, original provider authenticity, actual spreads, slippage, financing, and fresh untouched chronological holdouts remain unverified. Do not use this result to enable live or paper trading signals.

Run synthetic tests from `backend` with `PYTHONPATH=. python -m pytest -q tests/test_offline_m1_archive_deletion_stress.py`.
