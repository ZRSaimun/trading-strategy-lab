# Multi-fold cost scenario precommitment (offline, outcome-free)

`backend/app/declared_multifold_cost_precommit.py` provides
`prepare_declared_multifold_cost_scenario_set_sha256(folds)` and
`require_declared_multifold_cost_scenario_set_sha256(folds, expected_sha256)`.
Call the first **before** supplying any holdout outcome receipts. Store the
resulting lowercase SHA-256 outside the research environment in an
independently trusted, immutable, timestamped registry. The second function
compares the complete declaration against that previously retained digest.

Each of 2–24 chronological folds has **exactly** `manifest`, `census` and
`scenarios`. The existing fold-isolation audit rejects reused archive/row
identities, overlapping or reordered windows, changed candidate/source
conventions and violations of the declared label embargo. Every fold must
declare the same 1–8 scenario IDs and complete source-bound row-cost
adjustments, including explicit zero-cost rows. Per-fold scenario/row ordering
is canonicalized, while chronological **fold order and fold count are bound**.
Changing the cost component, exact decimal text, archive, candidate,
membership, scenario set or fold population changes the commitment or fails
validation. No outcomes, P&L, broker credentials or quotes are accepted.

This does **not** prove that all historical archives were included, that an
external timestamp or signature is genuine, that holdouts were untouched,
that any model was fitted without leakage, or that prices, spreads, financing,
FX, slippage and margin were executable. A caller can omit a fold *before*
creating the digest or fabricate its own registration; independent census
inventory and one-time release enforcement remain mandatory. Scenario
IDs are shared across folds but the row-specific declared amounts can differ.
The digest must not be mistaken for a profitability result or a demo/live
order authorization. No network, broker or order calls occur.
