# Frozen capacity-admitted pseudo-settlement drawdown (Loop 2)

`backend/app/frozen_capacity_drawdown.py` is a disconnected, offline, read-only diagnostic of **fixed-horizon pseudo-settlement** drawdown on frozen CRT/ICT bracket opportunities. It introduces no API route, database migration, scheduler, credentials, broker interface, production feature flag or real-money execution.

```python
from app.frozen_capacity_drawdown import audit_frozen_capacity_drawdown
report = audit_frozen_capacity_drawdown(
    frozen_manifest, frozen_paths, externally_preserved_manifest_sha256,
    cutoff_utc_minute=PREDECLARED_MONDAY_UTC_EPOCH,
    embargo_minutes=1440,
    max_positions=1, per_position_risk_bps=100,
    total_risk_budget_bps=200,
)
```

## What it measures

The strict existing bracket-population, chronological-embargo and full-horizon FIFO capacity audits run first. The new module independently reconstructs admissions from **only frozen signal timestamps and policy**, checking the complete admitted/rejected population and maximum simultaneous reservations against upstream counts. No historical early target or stop outcome releases a slot. An admitted hypothetical position's R outcome is booked at the **predeclared full-horizon end**, then ordered by signal time and path ID to break ties. This artificial convention avoids using realized exit times to change admissions, but **does not represent actual chronological fills, cashflows or intrabar equity**.

For every illustrative additional round-trip cost of **0, 5, 10 and 20 basis points**, each training/holdout path retains its conservative lower and upper net-R bounds. The pseudo-equity is a cumulative **sum of R × fixed initial-equity risk fraction**, without compounding. The maximum peak-to-trough drawdown starts from a zero baseline. The optimistic all-upper path gives a *lower bound* on possible maximum drawdown; the pessimistic all-lower path gives an *upper bound*. This follows because every contiguous interval loss is monotone decreasing in each component return. Report both bounds and final pseudo-equity bounds separately for training and holdout. Recompute admitted mean bounds independently and reject mismatches with the capacity auditor.

For each cohort and cost scenario, the report also gives **peak and trough event indices** for the minimum and maximum drawdown bounds. Event `0` is the initial zero baseline; event `N` is after the Nth hypothetical path is booked in fixed-horizon-end order. Equal equity peaks retain their earliest occurrence and tied maximum drawdowns retain the earliest trough. An all-nonnegative path reports `(0, 0)` rather than fabricating a drawdown. These are **pseudo-settlement event indices, not market timestamps, actual exit events, trade recommendations or proof of executable equity drawdown**. The regression suite exhaustively compares 3,125 short return sequences against an independent quadratic peak-to-trough oracle.

The report also measures **terminal underwater drawdown**, the maximum cumulative pseudo-equity across all booking events (including event zero) minus the final cumulative pseudo-equity. This is distinct from the historical maximum peak-to-trough episode. The exact monotone bounds use all-upper outcomes for minimum terminal underwater drawdown and all-lower outcomes for maximum terminal underwater drawdown, expressed as percentages of fixed initial equity. The exhaustive regression compares all 3,125 five-event histories against an independent all-prefix terminal-loss oracle. These are not actual broker cash balances, executable mark-to-market losses or proof of account recovery.

The report also records the **first later pseudo-settlement event** that regains the selected peak level for each minimum/maximum drawdown scenario. The recovery event is `null` if there was no positive drawdown or if the selected peak was never recovered before the last booking. This is a retrospective, fixed-horizon booking-index diagnostic: it is **not** an actual broker recovery time, intrabar cash balance, execution timestamp, forecast, or a reason to admit/reject any trade. The regression oracle checks both the selected peak/trough and first subsequent recovery against all 3,125 five-event sequences.

## Fixed initial-equity pseudo-loss barrier first passage

For each frozen training/holdout cohort and illustrative 0/5/10/20-bps additional round-trip cost, the report now includes **10% and 20% of fixed initial pseudo-equity** cumulative-loss barriers. Each event is a predeclared full-horizon pseudo-booking, not an observed fill or calendar timestamp. Touching the negative threshold counts as a breach.

- `first_possible_event`: earliest event at which the all-lower endpoint cumulative return touches the barrier; at least one interval-compatible synthetic outcome sequence can cross it.
- `first_unavoidable_event`: earliest event at which the all-upper endpoint cumulative return touches the barrier; every interval-compatible synthetic sequence has crossed by that event. This is a mathematical interval statement, **not** certainty about actual trading.
- `envelope_status`: `NOT_REACHED_WITHIN_INTERVAL_ENVELOPE`, `POSSIBLE_WITHIN_INTERVAL_ENVELOPE`, or `UNAVOIDABLE_WITHIN_INTERVAL_ENVELOPE`. A possible crossing cannot be labeled unavoidable; the possible event cannot occur later than an unavoidable event.

Both event fields are null when the corresponding endpoint never touches the threshold. The synthetic all-endpoint classification does **not** measure a probability, expected shortfall, margin liquidation, risk of ruin, broker stop, or capital adequacy. It is sensitive to the artificial fixed-horizon ordering and initial-equity risk convention. No thresholds are tuned against holdout outcomes, and these events must never influence retrospective admission, candidate selection, or trade authorization. Independent exhaustive all-path tests enumerate interval-compatible integer outcomes to verify the earliest possible and unavoidable crossing logic.

## Strict-negative pseudo-settlement streak envelope

Each cost scenario and cohort also reports
`{training|holdout}_pseudo_settlement_minimum_longest_strict_negative_path_streak`
and
`{training|holdout}_pseudo_settlement_maximum_longest_strict_negative_path_streak`.
A path counts as negative only when its **net-R outcome is strictly below zero**;
zero and positive paths break a consecutive-loss run. The metric counts adjacent
*full-horizon pseudo-bookings*, not trading days, calendar duration, broker
executions, or independent market bets. A loss streak may include overlapping
market exposure and does not imply broker solvency or margin outcomes.

With independently selectable interval-valued path outcomes, the **all-upper**
net-R endpoints minimize the longest negative streak, and the **all-lower**
endpoints maximize it. Both limits are exact mathematical bounds over the
declared synthetic outcome envelope, not likelihood estimates. An ambiguous
path is never optimistically discarded. Costs are the existing illustrative
0/5/10/20 additional round-trip basis points; they are not authenticated
executable spreads or financing. The independent exhaustive oracle checks
4,680 short synthetic interval-compatible histories, including exact-zero
breaks and sign-crossing intervals. These streaks must not be used for
candidate selection, live order authorization or claims of predictive edge.

## Strict-sign uncertainty census under additional execution costs

For each admitted training/holdout cohort and each **0/5/10/20 bps illustrative additional round-trip cost**, `{training|holdout}_pseudo_settlement_strict_sign_census` records the exact mathematical bounds on the number of *strictly positive*, *strictly negative*, and *exactly zero* hypothetical net-R outcomes. Each class has `guaranteed_...` and `possible_...` counts; `admitted_paths` is the complete timestamp-admitted population. A return interval spanning zero can be both a *possible* strict win and a *possible* strict loss, so possible class counts need not sum to the cohort size. Exact zero is neither a strict win nor a strict loss.

The lower endpoint establishes guaranteed positives and possible negatives; the upper endpoint establishes possible positives and guaranteed negatives. Both endpoints are required to be zero for a guaranteed exact-zero outcome. The diagnostic never selects favorable outcomes, discards ambiguous paths, or changes capacity admission. A monotonicity check refuses cost scenarios in which increasing additional costs creates possible/guaranteed pseudo-winners or removes possible/guaranteed pseudo-losers. The independent exhaustive test enumerates 4,680 interval-compatible synthetic histories and checks each sign-count bound against complete integer-outcome enumeration.

These counts are **not** observed profitable fills, broker win rates, probability intervals, calibrated forecasts, or evidence of statistical trading edge. Costs are hypothetical; no authenticated BID/ASK, financing, spread or slippage is inferred. No sign census may authorize a live or paper order.

No individual winning week, trade, or ambiguity is removed to improve returns. Declared exclusions, censored paths, inadequate cohort size/dispersion, wrong manifest hash, cutoff/embargo leakage, duplicate signals, inconsistent costs or changed admissions cause withholding or rejection. Synthetic regression tests verify baseline losses, cost ordering, ambiguous outcomes, rejection accounting, no hindsight capacity release, invariance to input order and fail-closed conditions.

## Explicit limits and coordination

These percentages are **not executable portfolio equity or risk-of-ruin forecasts**. Fixed-horizon booking may differ greatly from actual stop/target exit time; it excludes intrabar mark-to-market, variable contract sizes, margin, financing, currency conversion, slippage, gaps, forced liquidation, correlated portfolio cashflows and broker fills. The manifest SHA is caller-declared, not proof of independent preregistration. Source licensing, historical timestamp reconciliation and executable BID/ASK costs are not verified; no authenticated historical performance or profitable edge is established.

Loop 1 must resolve source rights, clock/DST collisions and executable quote provenance; Loop 3 must freeze policies and protect holdouts independently; Loop 4 must validate broker paper-account statements, cash/margin/FX liabilities and hard risk gates before any account-level simulation. This research utility must not be used to authorize a trade.


## Capacity-rejected opportunity-set sign census

The auditor also retains **all capacity-rejected frozen opportunities** in a separate
strict-sign uncertainty census for each training/holdout cohort and 0/5/10/20-bps
illustrative cost scenario. It independently checks that admitted and unadmitted
path IDs are disjoint and together equal the full audited population. Each
unadmitted census reports `unadmitted_paths` plus guaranteed/possible strictly
positive, strictly negative, and exactly-zero net-R counts. Zero rejected paths
produces explicit zero counts; ambiguous rejected paths remain ambiguous.
The same worsening-cost monotonicity check applies to both populations.

Rejected paths are **not** re-admitted retrospectively even if their historical
outcome was favorable. This census is an opportunity-set/selection transparency
diagnostic, **not** a backtest of an executable alternative strategy, a claim
of forgone profit, a reason to retune capacity using holdout outcomes, or evidence
of independent source/holdout authentication. It never authorizes a paper or
real-money order.


## Fixed bottom-quartile admitted net-R downside envelope

Each complete training/holdout cohort and each additional 0/5/10/20-bps
round-trip cost scenario now includes
`{training|holdout}_pseudo_settlement_worst_quartile_net_r`.
This reports the number of **timestamp-admitted** paths, the predetermined
bottom-quarter count `ceil(N/4)`, and exact
`minimum_worst_quartile_mean_net_r` /
`maximum_worst_quartile_mean_net_r` bounds. For each interval-compatible
realization, sort all admitted pseudo-net-R outcomes ascending and average
the worst `ceil(N/4)`. The all-lower and all-upper endpoint vectors attain
the exact extrema of this order-statistic mean, so ambiguous outcomes
remain uncertain. No outcome is discarded, no profitable trade is selected,
and capacity decisions remain timestamp-only and unchanged.

The quarter fraction is fixed in code, not selected after viewing holdout
results. Increasing declared additional costs must not improve either
bound; the auditor rejects nonmonotone cost reports. The synthetic tests
independently enumerate **9,800** complete interval-compatible histories
(including 5/6-path cases where two worst outcomes are averaged), and
verify no admitted-tail change when a capacity-rejected path's result changes.

This is a **retrospective worst-quartile average**, not a calibrated
expected-shortfall/CVaR forecast, tail probability, confidence interval,
actual broker drawdown, actual fills or statistical trading advantage.
Overlapping signals, synthetic full-horizon settlement, unverified
market-data provenance, financing and executable quote costs limit
interpretation. In particular, do **not** use this descriptive metric
to tune filters on an untouched holdout or authorize a trade.


## Per-path cost-trajectory integrity (26 October 2026)

Before reporting **any** cost scenario, the auditor now validates every eligible
frozen path's complete 0/5/10/20-bps additional round-trip cost trajectory,
including paths rejected by capacity. The lower and upper net-R endpoints must
each be non-increasing as the assumed additional cost rises; each scenario must
have the exact expected integer cost label and a valid ordered finite Decimal
return interval. One corrupted or missing trajectory raises an error and
withholds the entire report rather than silently dropping a path.

This is stricter than checking only cohort means, worst-quartile statistics or
win/loss counts. A path whose returns improve at a higher assumed cost can be
hidden by another path deteriorating more, leaving aggregate statistics
monotone. Synthetic tests explicitly exercise that masking case, both endpoint
violations, missing scenarios, inverted intervals and boolean cost labels.

**Scope:** This is a software-integrity guard, not evidence that 0/5/10/20 bps
represent real broker costs. It does not authenticate source archives, infer
spread/slippage/financing, establish profitable expectancy, unlock the holdout,
authorize an order or change capacity admissions. The draft feature remains
offline and unmerged until its production release gates are verified.


## Independent declared cost-erosion arithmetic (26 October 2026)

The full-population auditor now verifies **each eligible path**, including
capacity-rejected paths, against the *frozen* entry and stop plus the upstream
gross-R lower/upper endpoints. For each 0/5/10/20-bps scenario it independently
recomputes the **declared illustrative** round-trip cost in R units as

`abs(frozen_entry) × additional_bps / 10000 / abs(frozen_entry − frozen_stop)`

and requires both net-R endpoints to equal their respective gross-R endpoints
minus that cost. The arithmetic uses the upstream bracket evaluator's 50-digit
Decimal convention, with no floating-point conversion. A missing gross-R
endpoint, zero bracket risk, inverted gross interval, changed scenario identity,
or even a **monotone but undercharged** cost path now fails closed before
publishing any cohort result. Three synthetic regression cases include an
end-to-end corrupted upstream outcome.

This is a *consistency audit of the supplied research model*, not independent
validation of broker spread, bid/ask execution, fees, slippage, financing,
source authenticity or a real cost schedule. The declared risk distance is
not an account cash-risk budget. No scenario is optimized using holdout
outcomes, no capacity admission is changed, and no real or paper order is
authorized. The branch remains disconnected, draft and undeployed.

## Distinct optimistic/pessimistic drawdown peak event fields (26 October 2026)

Corrected a report-key collision: the **minimum** possible maximum drawdown
previously wrote its optimistic peak event into the
`maximum_max_drawdown_peak_event` key, which the pessimistic result then
overwrote. The report now exposes both
`minimum_max_drawdown_peak_event` and
`maximum_max_drawdown_peak_event`, each paired with its corresponding
trough, magnitude and recovery event. No drawdown arithmetic, frozen admission,
execution-cost assumption or order capability changed.

A synthetic regression makes the first holdout opportunity intrabar ambiguous,
so the optimistic path peaks at booking event 1 while the pessimistic path
peaks at event 0, and verifies both fields across all four cost scenarios.
These are retrospective fixed-horizon pseudo-booking indices, **not** actual
broker fill times or authenticated profitability evidence.

## Paired zero-cost guaranteed-winner erosion (26 October 2026)

For every frozen **admitted and capacity-rejected** path, retain the same
identity across declared 0, 5, 10 and 20-bps additional round-trip cost
scenarios. Count only paths whose *entire* zero-additional-cost net-R
interval is strictly positive. At each higher cost, count how many of those
baseline-guaranteed winners (a) are guaranteed no longer strictly positive
(higher-cost upper endpoint <= 0), (b) possibly no longer strictly positive
(higher-cost lower endpoint <= 0), or (c) remain guaranteed strictly positive
(higher-cost lower endpoint > 0).

This is a paired sensitivity diagnostic, not a win probability, executable
fill, proof of edge, trade recommendation or signal filter. It does not
alter frozen admission, and it preserves uncertainty. Zero additional cost
is not free execution. The audit fails closed on inconsistent paired
intervals or nonmonotone erosion across cost scenarios. Tests include an
independent discrete-outcome oracle and full-report population census.
Source rights, clock mapping, quote-side costs, financing, untouched holdouts
and trading profitability remain unverified.
