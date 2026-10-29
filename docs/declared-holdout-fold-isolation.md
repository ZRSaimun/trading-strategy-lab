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


## Declared unresolved-label population at window close

The audit also counts **all** census rows whose caller-declared
`label_available_at_utc` is strictly later than that fold's
`holdout_end_at_utc`. The per-fold
`declared_labels_pending_at_window_end_count` and study-wide
`total_declared_labels_pending_at_window_end_count` quantify how many
labels remain unobservable at the declared decision-window close.
`max_declared_labels_pending_at_window_end_count` and
`most_pending_declared_labels_fold_index` identify the largest per-fold
population, breaking ties toward the earliest zero-based fold; the index
is `null` when none are pending. Labels maturing exactly at window end
are not pending. Counts are separate from the longest maturity *duration*:
a one-second tail can affect many observations. All are bounded by the
validated census population and are **not** independent evidence of
actual source receipts, trade outcomes, holdout integrity or release
eligibility. They do not enable any trading permission.


## Prior-fold label availability at the next validation cutoff

A later fold may select its candidate **after** all earlier labels have matured
and still have a validation cutoff at which some earlier labels were not
observable. The membership audit now reports
`declared_validation_cutoff_transitions`: one entry per consecutive fold pair
with the zero-based `later_fold_index` and
`declared_prior_labels_unavailable_at_validation_end_count`.
For each transition it counts **all** previous-fold rows whose declared
`label_available_at_utc` is strictly later than the later fold's
`validation_end_at_utc`; equality is available. Study-level total, maximum
and earliest-later-fold tie index are reported as
`total_declared_prior_labels_unavailable_at_validation_end_count`,
`max_declared_prior_labels_unavailable_at_validation_end_count` and
`most_unavailable_at_validation_later_fold_index` (null when all counts
are zero). This is distinct from selection-time label embargo and from
labels pending at the *previous window's* close.

**Interpretation:** A positive count is a *potential data-lineage audit
question*, **not** proof of look-ahead leakage. A later validation may
legitimately use entirely separate training/validation data and never touch
previous holdout labels. A zero count likewise cannot prove no leakage.
These are caller-declared clocks, not authenticated observation receipts,
source access logs, an independently protected holdout or evidence of profit.
No outcomes, cost estimates or order permissions are accessed or enabled.
Synthetic regressions cover exact cutoff equality, one-second unavailability,
populations, deterministic ties and validation ending before the earlier
holdout window closes.


## Declared decision-time coverage and long inactive tails

A multi-year declared holdout window does **not** imply observations were
distributed throughout those years. For each fold, the audit reports
`first_declared_decision_at_utc`, `last_declared_decision_at_utc`,
`declared_decision_span_seconds` (last minus first),
`max_declared_interdecision_gap_seconds` (null for one observation), and
`declared_last_decision_to_window_end_seconds` (end minus last decision).
At study level, `max_declared_last_decision_to_window_end_seconds` and
`longest_declared_last_decision_gap_fold_index` identify the largest trailing
interval, breaking ties toward the earliest zero-based fold. These metrics
come from validated, strictly increasing declared decision timestamps; they
do not inspect prices, labels' values, P&L or licensed source archives.

For example, forty daily observations beginning in January can occupy only
39 days of a declared two-year window. That is a **sampling concentration
warning**, not evidence that the source lacked market data: a strategy may
legitimately generate no decisions for long periods. The metric cannot
establish continuous market coverage, a representative walk-forward sample,
authenticated timestamps, broker fill availability or profitability.
Synthetic regressions cover 40 early daily decisions, a one-observation
fold, and a last decision two seconds before the final window closes.
Trading permissions remain disabled.
