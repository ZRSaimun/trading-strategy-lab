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

No individual winning week, trade, or ambiguity is removed to improve returns. Declared exclusions, censored paths, inadequate cohort size/dispersion, wrong manifest hash, cutoff/embargo leakage, duplicate signals, inconsistent costs or changed admissions cause withholding or rejection. Synthetic regression tests verify baseline losses, cost ordering, ambiguous outcomes, rejection accounting, no hindsight capacity release, invariance to input order and fail-closed conditions.

## Explicit limits and coordination

These percentages are **not executable portfolio equity or risk-of-ruin forecasts**. Fixed-horizon booking may differ greatly from actual stop/target exit time; it excludes intrabar mark-to-market, variable contract sizes, margin, financing, currency conversion, slippage, gaps, forced liquidation, correlated portfolio cashflows and broker fills. The manifest SHA is caller-declared, not proof of independent preregistration. Source licensing, historical timestamp reconciliation and executable BID/ASK costs are not verified; no authenticated historical performance or profitable edge is established.

Loop 1 must resolve source rights, clock/DST collisions and executable quote provenance; Loop 3 must freeze policies and protect holdouts independently; Loop 4 must validate broker paper-account statements, cash/margin/FX liabilities and hard risk gates before any account-level simulation. This research utility must not be used to authorize a trade.
