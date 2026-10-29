# Row-specific declared holdout adverse-cost stress (offline)

`backend/app/declared_holdout_row_cost_stress.py` audits **1–8 caller-declared scenarios** against the full existing holdout release and exact-decimal cost attribution gate. Each scenario must contain **exactly one adjustment for every census observation**, including explicit zero-cost rows. This prevents silently omitting expensive trades from a scenario.

Each adjustment binds `observation_id`, `row_sha256`, and `source_sha256` to the validated holdout census, then supplies five **additional nonnegative settlement-currency cash debits**: spread, slippage, commission, financing and FX. The audit rejects missing/duplicated/foreign observations, negative or malformed money, inconsistent source or row identities, duplicate scenario IDs and unknown schema fields. It does **not** alter the original outcome records.

For released populations (30+ observations), the audit reports exact-decimal additional costs by component, total incremental cost, maximum per-observation additional debit, stressed net cash and worst scenario. Scenarios and adjustment rows are order-invariant; ties use lexical scenario ID. For populations of 1–29, **all** outcome-dependent amounts, cost totals, receipt digest and worst-scenario details are withheld, even though all inputs are validated.

Unlike the existing `declared_holdout_cost_scenarios.py` module, which applies a fixed additional cash debit to **every** observation, this module supports variable per-observation adverse costs. The new inputs are **not** market prices, percentage spreads, executable BID/ASK quotes, validated CFD overnight rates, or evidence that any historical backtest was profitable. Per-row adjustments could themselves be fitted to outcomes; a trusted external preregistration and protected holdout are still required to prevent selection bias. Source authenticity and time-zone eligibility remain blocked pending [issue #153](https://github.com/ZRSaimun/trading-strategy-lab/issues/153).

Synthetic tests: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_declared_holdout_row_cost_stress.py`. No production route, importer, database, licensed archive, credential, paper or live order adapter is modified. `may_execute_demo_order` and `may_execute_real_order` are always false. Do not merge or deploy without complete exact-head CI, independent backup restore, rollback rehearsal and authenticated health checks.


## Receipt-time stressed cash risk (synthetic / declared only)

Each released scenario also reconciles **per-observation stressed net cash** and
reports the worst observation, maximum drawdown of cash totals at **receipt-second
boundaries**, and a conservative maximum over all possible within-second receipt
orderings. All three are null below the 30-observation withholding threshold.
Receipt order is determined by declared observed_at_utc, not trade-decision
order, because overlapping positions can close out of order. Scenario totals
are independently reconciled against the sum of per-row stressed cash.

The within-second ordering diagnostic can be larger than the second-end
drawdown, but it is **not** a bound on unobserved intraperiod mark-to-market
equity, margin liquidation, bid/ask execution, or broker financing. Both clocks
and all costs remain caller-declared and unauthenticated. No order permissions
are granted.

## Adverse-cost-induced losing observations

For released populations (at least 30), each scenario additionally reports the
number of observations with **negative declared net cash** before stress, the
number with negative net cash after stress, and the subset that became negative
**only after additional adverse costs**. Exact-zero baseline net is non-losing;
a one-unit (0.0001 settlement-currency cash) extra debit can make it losing.
The report also gives the sum of absolute stressed negative observation cash
amounts (`stressed_gross_loss_cash`), without offsetting profitable rows.
These four fields are `null` for populations below 30.

Because all extra costs must be nonnegative, the losing-observation population
cannot shrink under stress. The metrics reconcile against source/row-bound
receipt outcomes; no inferred intratrade price path, margin, drawdown, risk
probability or statistically validated loss frequency is implied. Observations
are not guaranteed independent trades, and the declared source, cash and
receipt identities are not externally authenticated. No trade permissions
are granted.

## Additional-cost concentration (declared scenarios only)

For released holdouts (30+ observations), each scenario also reports
`additional_cost_affected_observation_count`: the number of rows with any
strictly positive additional debit; and
`max_single_observation_extra_cost_share_bps`: the largest per-row debit
as a **floor-rounded integer share of total incremental cash costs** in basis
points (10,000 bps = 100%). This flags stress scenarios dominated by a single
row rather than spread across the sample. If total incremental cost is zero,
the share is `null` (undefined), not zero. For fewer than 30 observations,
both values are `null` to preserve outcome-release withholding policy.

These describe **caller-specified stress allocations**, not independently
measured market costs, tail probabilities, broker equity, expected drawdown,
or a profitability result. A high concentration may be deliberate; it is a
research-review flag rather than an automatic model rejection. The metric
never grants demo or real order permissions.


## Cost-induced loss severity and stressed-loss concentration

For released populations (30+ observations), each scenario also reports
`additional_cost_induced_gross_loss_cash`: the exact sum of negative stressed
row-net cash magnitudes **only for rows that were nonnegative before stress**.
This measures how much declared gross loss arose on newly losing rows; it does
not treat further deterioration of an already losing row as a newly induced
loss. It must be no greater than `stressed_gross_loss_cash`.

`max_single_stressed_loss_share_bps` is the largest individual stressed
negative row-net magnitude divided by the scenario's total stressed gross
loss, expressed as a floor-rounded integer number of basis points. When no
rows lose money, the share is `null` (undefined), not zero. Both metrics
remain `null` below the 30-observation release threshold. They are
independent of input row order and use exact-decimal cash arithmetic.

These are **caller-declared loss-severity diagnostics**, not an estimate of
value at risk, independent trades, executable slippage, broker equity, or a
profitable edge. A high share may simply reflect a single constructed stress
row. No demo or real order permissions are enabled.


## Positive declared-net erosion under adverse costs

For released populations with **positive** caller-declared baseline net cash,
`additional_cost_share_of_positive_baseline_net_bps` is the floor-rounded
ratio of total scenario additional cash debits to baseline net, in basis
points. It can exceed 10,000 bps when the extra costs exceed baseline net.
`positive_baseline_net_erased_by_stress` is true only when a strictly
positive declared baseline becomes **zero or negative** under additional
costs. For zero/negative baseline net, the ratio is undefined (`null`)
and the erosion flag is false. Both fields are `null` when fewer than
30 observations are eligible for release.

The denominator includes the existing signed CFD financing cash and all
declared spread, slippage, commission and FX costs. This is a deterministic
**cost-fragility accounting diagnostic**, not a calibrated break-even
probability, independently verified edge, or broker-executable cost.
It does not grant any paper/demo or live order permission.


## Positive observation erasure under row-specific costs

For released populations (30+ observations),
`additional_cost_erased_positive_observation_count` counts rows with
**strictly positive** baseline net that become **zero or negative** after
additional declared cash debits. This is distinct from the existing
cost-induced *losing* count: exact zero is no longer profitable, but it is not
a negative loss. Previously nonpositive rows never count as erased wins.

`positive_observation_cash_eroded_by_stress` sums, for each initially
positive row, the smaller of that row's additional cost and its original
positive net cash. This measures the amount of **original positive cash
consumed**, without counting an overshoot below zero twice as erased gains.
It uses exact-decimal arithmetic, signed baseline financing and full
source-bound row coverage; the sum is zero if no positive row is affected.
Both metrics are `null` for fewer than 30 observations. They are descriptive
of caller-declared cash outcomes, **not** independently verified profitable
trades, broker fills, executable costs, or predictive performance. Neither
metric grants demo or real order permission.


## Pairwise row-wise cost dominance and incomparable stresses

The offline audit now compares all pairs among the 1–8 complete scenarios using
**total additional settlement-currency cash per observation**. A scenario is
*row-wise more adverse* only when its additional debit is at least as large
for **every** identical source-bound observation. Matching aggregate totals
are insufficient: if one scenario charges row A more and row B less, the pair
is **incomparable**, even when both scenarios have identical total cash cost.

For released populations (30+), `scenario_cost_dominance_pairs` lists
the deterministic lower-or-equal/higher-or-equal scenario IDs and whether
all per-row totals match exactly; equal vectors use lexical ID order.
`scenario_cost_incomparable_pair_count` counts pairs that cannot be
ordered by row-wise adverse cost. The implementation also asserts that
row-wise dominance cannot improve stressed net cash, reduce negative-row
counts or gross losses, reduce positive-profit erasure, or improve the worst
stressed row. These checks use exact-decimal arithmetic. Both new report
fields are `null` below 30 observations.

**Do not infer** monotonicity of receipt-time drawdown from cost dominance:
the maximum drawdown measured from a changing prior peak can behave
differently as earlier costs increase. This diagnostic does not rank
incomparable scenarios, authenticate source data, independently protect
a holdout, prove broker-executable costs or establish profitability.
No broker adapter or order permission is changed.

## Negative receipt-batch clustering (declared-only cash diagnostic)

For released populations of at least 30 observations, each scenario now
aggregates stressed cash receipts by their declared `observed_at_utc` second,
then reports `negative_receipt_batch_count`,
`max_consecutive_negative_receipt_batches` and
`max_consecutive_negative_receipt_batches_loss_cash`. The last is the
largest sum of negative batch cash magnitudes within any uninterrupted run
of negative batches. A zero or positive net batch breaks the run; when
there are no negative batches the count, longest run and loss are zero.
All three fields are `null` for smaller holdouts.

**Consecutive means consecutive entries in the ordered observed-second
batch sequence, not adjacent wall-clock seconds.** A gap of days between
two negative receipt batches does not imply an uninterrupted account loss
throughout those days. A same-second positive and negative receipt can
net to a nonnegative batch, so individual losing observations need not
equal negative receipt batches. This is a cash-posting clustering
diagnostic only; it is not a loss-streak probability, independent-trade
statistic, intraperiod broker-equity drawdown, margin estimate or a bound
on unobserved execution risk. All receipt times and costs are declared,
not independently authenticated. It grants no paper/demo or live order
permission.


## Canonical scenario-set input commitment (audit trace, not attestation)

The result includes `scenario_set_sha256`, an SHA-256 of a canonical JSON
envelope containing the **declared manifest digest**, **holdout census digest**,
protocol version, and the complete set of scenario IDs and per-row cost
adjustments. Scenario IDs and adjustment rows are sorted by their validated
identities before hashing, so caller list order does not affect the digest.
JSON object keys are canonicalized by the existing repository hash helper.
Exact input cash **strings** are preserved: `"0.1"` and `"0.1000"` have the
same numeric cash value but intentionally different evidence digests.
Changing the affected observation, cost component, amount, candidate, or
source-bound census changes the commitment.

This digest depends only on **declared pre-outcome inputs**. It does not include
outcome receipts, P&L, or the release timestamp; it can therefore be committed
to a genuinely independent timestamped registry **before** viewing holdout
outcomes. For 1–29 observations, it is still available, but outcome receipts
and every outcome-dependent amount remain withheld.

**Critical limitation:** generating or displaying a digest *after* seeing
results is not preregistration. This function neither checks an external
immutable registry nor prevents multiple candidate/scenario probes or
selective publication. No externally authenticated anchor, independently
untouched holdout, source provenance, executable broker cost, trading edge,
or paper/live order permission is established by this digest.

Synthetic regressions verify input-order invariance, candidate binding,
component/row/cash-text sensitivity, outcome independence and withholding.
