# Quote-driven paper execution engine (research-only, v1)

`frontend/lib/paper-execution.ts` introduces an independent, in-memory, deterministic `PaperExecutionLedger`. It does **not** call a broker, connect to Trading 212, issue orders, persist records, trade live or replace the historical OHLC simulator. It is deliberately **not exposed in the production UI** until a licensed, owner-authorized source of independently verifiable time-stamped bid/ask quotes is available.

## Inputs and identity

Construct one ledger for one exact instrument/provider/venue with a positive currency-per-point-per-unit multiplier and explicit `priceSide: 'bid-ask'`. Supply external quote events containing `observedAt` and `receivedAt` as Unix seconds, bid and ask, in strictly increasing observed-time order. Future timestamps, crossed/negative quotes, source mismatches, and duplicate/out-of-order events are rejected. The provider/source metadata is a declared identity, not a guarantee of quote authenticity or executable liquidity.

Orders have unique client IDs, exact instrument, BUY/SELL side, fractional research units, submission and expiry times, stop, target, maximum spread, maximum quote age, hypothetical stop-risk cap, adverse slippage per side and commission per unit per side. Only one pending/open order per ledger is allowed. Re-submitting an identical ID/body is idempotent; changing an existing ID's request is rejected. Cancellations apply to pending orders only.

## Causal event model

- Entry waits for a quote observed strictly **after** submission and received before order expiry; it will not fill from a quote already available at submission, from a stale quote, or above the user-set spread cap.
- **All** accepted state-changing events (submission, cancellation, quote receipt) advance one non-decreasing action-time clock. An old quote cannot be replayed after a later cancellation or submission to rewrite simulated history. Exact duplicate order-ID retries remain idempotent without advancing time. This is event-order protection, **not** proof that externally supplied timestamps are genuine.
- Paper BUY enters at ask + assumed adverse slippage; SELL enters at bid - assumed adverse slippage. An invalid bracket or a hypothetical stop loss exceeding the configured risk cap is rejected before filling.
- Protective exits are evaluated only on subsequent **fresh** quote events. BUY stops use bid and SELL stops use ask. If the quote gaps beyond the stop, the simulator fills at the worse observed executable side plus adverse slippage rather than assuming the stop price is guaranteed. Targets fill at the target with no favorable improvement assumed.
- The explicit `costs` output is round-trip **commission only**; spread and slippage are embedded in simulated entry/exit prices. Financing, borrow fees, currency conversion, variable slippage, price impact, depth/partial fills, exchange calendars, margin liquidation and broker-specific contract specifications are **not** modeled.
- **Numerical fail-closed checks:** stop-risk calculations that underflow to zero reject entry; a protective gap fill that would imply a zero/negative price, or a simulated exit with non-finite gross, commission or net P&L, raises an error and leaves the position OPEN without consuming the quote timestamp. This is not a realistic model of extreme negative-price markets or broker settlement; it is a safety boundary until contract-specific execution rules are available.
- A stale quote does not trigger a fabricated exit. If a later fresh quote appears beyond a stop, the simulator may record a worse fill. It does not model what could have happened during missing quotes. Expiry occurs when a later quote is received; there is no background timer.
- Closed orders cannot be changed by future quote events. State is held in memory; callers must not treat it as a durable, independently reconciled brokerage ledger.

## Verification

From `frontend/` run:

```bash
node --experimental-strip-types --test tests/paper-execution.test.ts
```

Sixteen deterministic tests cover quote freshness, causality, adverse BUY/SELL gap exits, quote-source isolation, idempotent client IDs, cancellation, expiry, wide spreads, risk rejection and settled-order invariance. Existing frontend/backend/Docker/cloud CI must pass on the proposed PR before merge. No historical profitability was evaluated by these synthetic quote tests.

## Handoff and activation gates

1. Add source-authenticated streaming bid/ask market data for a permitted exact broker instrument and verify exchange/OTC clock conventions, timestamp delays and provider licensing.
2. Introduce a **durable** idempotent paper journal with replay checkpoints and restart reconciliation; do not claim that this in-memory engine alone can handle a disconnected client or partial fills.
3. Add CFD overnight financing, contract multiplier, margin and forced-liquidation scenarios; record the rate's provenance and the time of each funding event. Never silently assume a fixed overnight charge from BID-only archives.
4. Implement user-visible paper order lifecycle with clear `SIMULATED` labels and separate reconciliation tests against broker demo fills. No real-money routing without owner-confirmed per-order instructions and hard server-side risk gates.

This is a testable software component, not evidence of a trading edge, achievable execution price, or profit.

## Explicit posted financing/FX cashflows (experimental)

The separate [paper cashflow reconciler](paper-cashflow-reconciliation.md) can apply **explicitly supplied** overnight financing, borrow, FX and broker adjustment entries to an already-closed simulated order without modifying its execution ledger. It checks exact source identity, event-time cutoffs, duplicate IDs and base price/commission P&L integrity. Nine synthetic tests pass locally. This is not automatic CFD funding-rate modeling: missing charges remain unknown and output is always labelled PARTIAL_UNVERIFIED. It is not wired to a broker or the production UI.
