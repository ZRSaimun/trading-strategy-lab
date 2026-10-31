# Disconnected paper account drawdown fence

This module adds a **read-only**, fail-closed money-management review for
hypothetical paper-account equity snapshots. It is not a trading endpoint.
Import `review_paper_account_drawdown` from
`app.paper_account_drawdown_fence` and provide a declared policy, a current
checkpoint, a previous checkpoint, and a trusted server UTC millisecond clock.

## Checks

* Exact account/provider/currency matching, contiguous sequence and monotonic
  observation/receipt times; no acceptance without a previous checkpoint.
* Snapshot freshness at most 3 seconds, transport delay at most 1 second.
* UTC-day consistency, stable day-start equity, nondecreasing all-time equity
  peak and no unreceipted loss-streak reset. Midnight rollover is held for
  separate independently authenticated reconciliation.
* Exact-decimal equity = balance + unrealized P&L on both snapshots.
* Conservative peak-to-current and day-start-to-current drawdown calculations.
  Both include declared outstanding stressed risk as additional downside.
* Minimum remaining free-equity buffer after declared margin and reserved
  downside; consecutive-loss circuit-breaker threshold.
* Strict finite, bounded decimal strings and integer clocks. A SHA-256
  fingerprint binds policy, both snapshots and review time.

The policy caps cannot be relaxed beyond 20% peak drawdown or 10% intraday
drawdown; minimum free-equity buffer cannot be below 10% of equity; the loss
streak threshold cannot exceed 10. These are conservative *review ceilings*,
not regulatory requirements, a guarantee of loss containment, or a suggestion
that these large losses are acceptable. Owners should normally select
substantially tighter limits.

Every result returns `status=HOLD_RECONCILIATION`,
`may_execute_paper_order=false` and `may_execute_real_order=false`,
**including when every structural assumption check passes**.

## Limits and next integration

Caller-provided equity, peak, margin, risk reservations and loss streak are
**unauthenticated**. The unkeyed SHA-256 is not a signature, independent
checkpoint anchor, broker receipt, or proof of a continuous record. Declared
peak and day-start balances can be fabricated; sequence numbers do not prove
no events were omitted. Equity arithmetic presumes all amounts are in the
same account currency; FX conversion, financing, gap losses, and broker
liquidation are not verified. No write, API route, broker connection,
credential, order, paid resource, or database migration is introduced.

Future integration requires a licensed authenticated account/position source,
currency conversion with source timestamps, immutable checkpoint storage,
transactional reservations, independently anchored audit logs, verified
terminal fills and stop acknowledgements, and human approval per actual
live order. The existing paper daily-loss latch and persistent risk reservation
work must remain independently enforced. Do not treat this offline review
as a substitute for those controls.

Run the synthetic regression suite with:

`cd backend && PYTHONPATH=. pytest -q tests/test_paper_account_drawdown_fence.py`
