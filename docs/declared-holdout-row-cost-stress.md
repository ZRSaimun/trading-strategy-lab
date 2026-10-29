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
