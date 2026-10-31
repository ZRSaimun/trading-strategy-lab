# Paper order / portfolio cross-check (Loop 4)

This read-only bridge integrates the existing `live_order_review` one-order
preview with `paper_group_concentration_guard` and its underlying
`paper_account_exposure_guard`. It does **not** connect to a broker, store
credentials, reserve risk, create an order, send a request or expose an API route.

`evaluate_paper_order_portfolio_crosscheck(order, account_snapshot, group_policy,
now_ms=trusted_server_utc_ms)` recomputes both guards with the **same server
clock**. The proposed order must occur exactly once as a PENDING exposure in the
declared account inventory. Identity, source, direction, quote timestamps,
prices, quantity, costs, account P&L and risk policies must agree. Existing
notional, margin and stressed-risk reservations must equal the summed other
exposures, including adverse executable-side stress. It also independently
enforces review-policy ceilings: 3s quote age, 1s transport delay, 100bps
spread, 5x gross leverage, 5% position-risk budget and 10% daily-risk budget
relative to declared equity. These are review-policy ceilings, **not**
broker-specific limits or a recommendation to risk those amounts.

A structurally consistent result has `structural_checks_pass=true`, but its
status **always** remains `HOLD_RECONCILIATION` and both execution flags are
**false**. A SHA-256 digest is diagnostic only, not a signature, approval or
broker receipt. Recalculate after any inventory, quote, order or policy change.

## Important limitations

- Both inputs are caller declarations; there is no authenticated account,
  full-order inventory, stop acknowledgement, point-value/FX verification,
  exchange calendar, broker quote provenance or one-time approval.
- The quote ID in the single-order review cannot be matched to an account
  inventory quote ID because the existing exposure schema has none. Matching
  timestamps and prices is **not** quote-source authentication.
- PENDING orders are included in hypothetical exposure; a cancellation or
  timeout never releases a risk reservation. A separate transactional store
  and broker reconciliation are required.
- The module is not an execution gateway. Never convert its structural
  status into order permission. Trading 212's documented public API supports
  Invest/Stocks ISA only, not CFD accounts, and its order submissions are
  non-idempotent. See https://docs.trading212.com/api/orders/orders .
- No real-money order is permitted without supported provider credentials and
  explicit owner confirmation for that **individual** order. Stop losses may
  slip or gap; no profit or maximum-loss guarantee exists.

## Verification

`cd backend && PYTHONPATH=. python -m pytest -q
tests/test_paper_order_portfolio_crosscheck.py`

The tests use synthetic data only. Integration with persistent reservations,
the append-only journal, broker inventory, authenticated quote custody,
process-crash recovery and deployment is a future handoff. No migration,
credentials, production data or paid resources are changed by this PR.
