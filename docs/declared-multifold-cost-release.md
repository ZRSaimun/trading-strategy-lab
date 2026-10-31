# Declared multi-fold cost release (offline, fail-closed)

`backend/app/declared_multifold_cost_release.py` exposes
`audit_declared_multifold_cost_release(folds, expected_scenario_set_sha256, release_at_utc)`.

First construct 2–24 source-disjoint, chronological `manifest` / `census` /
`scenarios` declarations and use
`prepare_declared_multifold_cost_scenario_set_sha256` **before any outcomes
are accessed**. Preserve that digest in an independently trusted timestamped
registry. At release, each fold must have exactly those three fields plus
`anchor` and `outcomes`; the same release UTC second is used for every
fold. The existing precommitment, fold isolation, anchor and per-row release
audits must all pass. Duplicate outcome receipt hashes **across folds** fail.

The release returns aggregate baseline and stressed settlement-currency cash
results, per-scenario additional costs, worst fold and number of negative
folds. It reports no profit probability or executable return.

It also reports, for each predeclared cost scenario, the number of folds with
positive stressed net cash, the minimum and maximum **leave-one-fold-out**
stressed net cash, and whether removing any single fold would leave a
nonpositive aggregate. These are concentration/fragility diagnostics computed
from the *same fixed committed fold cohort*; they must never be used to
retrospectively drop an unfavorable fold, reselect a candidate, or claim a
profitable strategy. A zero remainder is nonpositive. They are withheld along
with all other outcome metrics if any fold contains fewer than 30 observations.
 **If any fold
contains fewer than 30 observations, every fold and aggregate outcome metric
and receipt digest is withheld** (including otherwise sufficiently populated
folds). Invalid or incomplete outcomes reject the entire release. Distinct
archive hashes are not proof of independent market feeds.

This is a pure, stateless, read-only research audit. Caller-supplied anchors,
clock values, receipts and the expected digest cannot independently establish
when a commitment was recorded, whether archives were authentic, or whether
the holdout was previously inspected. A trusted external registry and
one-time release lock remain required. Transaction costs are caller-declared
cash amounts, not verified broker BID/ASK, slippage, CFD financing, FX or
margin. Intraperiod account-equity risk is not measured. No paper or real
orders, broker APIs, secrets, licensed archives or production routes are used.
