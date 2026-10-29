# Declared cross-fold holdout isolation (offline research only)

`backend/app/declared_holdout_fold_isolation.py` checks **membership only** for 2–24 ordered, distinct-source declared holdout windows of one fixed candidate. It reuses the strict manifest and census validators in `declared_holdout_release_gate.py` and rejects outcome fields entirely. It does not fit models, release labels, calculate P&L, call a broker, or authorize paper/real orders.

The audit rejects reused archive SHA-256 declarations, reused raw-row hashes, overlapping or out-of-order holdout windows, later selection inside an earlier holdout, earlier fold labels that are not mature plus embargo before later selection, and changes to study/candidate/config or provider, venue, account, quote side, currency, UTC convention and instrument. Identical observation IDs may be used in different folds only when archive and raw-row identities differ; IDs are local to their declared fold. Reports counts, caller-declared manifest/source hashes, `min_declared_interfold_selection_gap_seconds` (minimum nonnegative interval between a prior holdout end and the next candidate selection), `tightest_declared_selection_gap_later_fold_index` (zero-based later fold; ties choose earliest), `tightest_declared_label_embargo_later_fold_index` (zero-based index of the later fold in the most restrictive transition; ties choose the earliest), and `min_declared_label_embargo_slack_seconds`: the smallest nonnegative difference, in seconds, between each later selection and the previous fold's latest declared label availability plus the later fold's embargo. Zero is an accepted boundary for either gap, not evidence of independently enforced isolation. This is only a diagnostic of **caller-declared clocks**; it cannot establish authentic timestamps, prevent outcome peeking or certify absence of data leakage. It never reports realized outcomes.

**Limitations:** This is not a source-authenticated walk-forward, an independently preregistered untouched holdout, proof of distinct market-data samples, or a broker-cost backtest. Distinct digest strings can be fabricated, and no cryptographic authentication of archive bytes or historical quote execution is performed. The fixed-candidate rule is intentionally narrower than retrained walk-forward strategies; development-fold audits remain in separate PR #144. For genuinely prospective holdouts, precommit eligibility rules before future market rows exist, then authenticate and freeze the observed census. A caller with access to raw outcomes can still peek. No result is evidence of profitability.

Synthetic regression: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_declared_holdout_fold_isolation.py`.


## Declared label maturity beyond the window

The membership-only audit now reports each fold's
`latest_declared_label_available_at_utc` and
`declared_label_tail_beyond_window_seconds` (zero if every label matures
before or at the declared holdout end). The study-level
`max_declared_label_tail_beyond_window_seconds` and
`longest_declared_label_tail_fold_index` identify the longest positive
tail, with earliest-fold tie handling; the index is `null` when all tails
are zero. This surfaces a release-readiness concern: the end of a
decision window does not mean every trade outcome is yet observable.
A positive tail is not itself leakage or proof of an invalid split.
The existing next-selection embargo validation still rejects immature
earlier labels. These values use only caller-declared timestamps; they
cannot verify actual source clocks, observation receipts or independence.
