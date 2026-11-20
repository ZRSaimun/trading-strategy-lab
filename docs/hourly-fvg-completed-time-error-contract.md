# Completed-hour timestamp mutation regression

The synthetic regression `frontend/tests/hourly-fvg-completed-time-mutation.test.ts`
now requires the **specific completed-field snapshot integrity error**, not a
generic timestamp ordering, validation, or other exception. A later unrevealed
hour's timestamp accessor tries to rewrite an already snapshotted completed
BID bar's UTC timestamp; the scanner must detect the rewrite without reading
any future OHLC, volume, or minute-coverage getter.

A broad exception regex could allow an unrelated failure to masquerade as
successful integrity enforcement. The test deliberately uses no real prices,
licensed data, verified volume receipt, broker BID/ASK quote, or execution.
It does not establish strategy profitability or production readiness. Keep
PR #157 draft, paper-only, unmerged and undeployed pending exact-head CI.
