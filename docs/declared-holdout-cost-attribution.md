# Offline declared holdout cost attribution

`audit_declared_holdout_cost_attribution(manifest, census, anchor, outcomes, release_at_utc)`
is a disconnected accounting view of the existing declared holdout release gate.
It invokes the complete release audit **before** computing any cost breakdown:
exact census membership, source binding, receipt uniqueness, observed-time
chronology, and the same one-time-release *limitation* apply.

For at least 30 observations, it reports exact four-decimal sums of gross,
spread, slippage, commission, FX, signed financing, separate financing debits
and credits, nonfinancing charges, signed net costs, and reconciled net cash.
Positive financing is a debit; negative financing is a credit. The identity is
`net_cash = gross_cash - (spread + slippage + commission + fx + financing)`.
A financing credit can make signed net costs smaller, but cannot be
misclassified as a negative spread or negative commission.

For 1–29 observations **all** outcome-derived totals and the receipt digest
are null; the wrapper does not circumvent the existing holdout withholding.
Inputs remain unchanged; receipt ordering does not change the aggregates.
Malformed, duplicate, cross-source, premature or negative execution-charge
receipts are rejected by the underlying gate. Synthetic tests cover cost
stress, signed credits, withheld populations, source identity, and order
invariance.

**Research limitation:** Every input, receipt, clock, cost and source digest
is caller-declared, not independently authenticated. This module does not
provide broker BID/ASK quotes, realistic market-impact slippage, CFD funding
schedules, account-currency conversion proof, mark-to-market equity drawdown,
protected walk-forward holdouts or evidence of profitable performance.
It does not submit demo or real orders and permanently denies trading
permission. Do not publish licensed historical archives. Do not merge or
deploy until full exact-head CI, independent production backup restoration,
rollback rehearsal and authenticated health checks are verified.
