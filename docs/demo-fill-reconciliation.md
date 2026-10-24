# Declared demo-fill versus paper-execution comparison (research-only)

`frontend/lib/demo-fill-reconciliation.ts` implements a pure, opt-in **read-only** comparison between a **CLOSED** simulated `PaperOrder` and independently supplied demo execution records. It does not fetch broker data, authenticate statements, place orders, call Trading 212, connect to a real or demo account, or change the production website. No executable broker adapter is installed.

## Required evidence and comparison gates

The caller supplies an exact paper source identity (instrument/provider/venue/point value), a separate declared demo source (broker order ID, account alias, statement SHA-256 and settlement currency), an explicit declared paper settlement currency that must match, an as-of timestamp, an allowed execution-time skew, and a list of explicit fills. Each fill has a unique execution ID, paper client ID, broker order ID, entry/exit leg, side, quantity, execution price, execution/receipt timestamps, commission, and matching source fields. **A digest string is not proof that a statement was actually downloaded or authenticated.** The caller must separately verify the document, provider/account, contract multiplier and currency. Paper orders currently lack a settlement-currency field; the caller must explicitly supply a paper currency and independently establish its authenticity before interpreting a numeric difference. A mismatched declared currency fails closed.

The comparison rejects cross-provider/account/venue/order/currency records, extra fields, future-dated fills, impossible prices/fees, nonfinite arithmetic, overfills, exits preceding sufficient entries, conflicting execution IDs and forged paper P&L/commission or invalid paper fill chronology. Identical repeated execution IDs are counted only once. Multiple partial fills are combined using quantity-weighted entry/exit prices and explicitly supplied commissions. Missing quantities return `INCOMPLETE` with **null P&L**, and completed fills outside the declared time tolerance return `TIMING_MISMATCH` with **null P&L**. Only complete and timely records return `COMPARABLE_UNVERIFIED`, with known-charge net difference to the paper model.

All results remain `DECLARED_SOURCE_ONLY_FINANCING_UNKNOWN`: no claim of broker authentication, liquidity, fill availability, financing completeness, currency conversion, profitability or real execution. Positive differences can reflect different timing, missing fees, contract specifications or bad input rather than strategy edge. This module does not simulate partial order cancellation, rejected demo orders, margin calls, swaps, borrow/FX fees or broker account balances. Do not use it to authorize live trading.

## Test and activation status

From `frontend`:

```sh
node --experimental-strip-types --test tests/demo-fill-reconciliation.test.ts
```

Eleven deterministic synthetic tests cover complete multi-fill VWAP and fee math, incomplete fills, duplicate-ID idempotency, source isolation, invalid/future fills, overfill/overflow, timing mismatch, forged paper P&L and extra-field rejection. These tests use **no actual demo broker data** and cannot establish profitability. Before integration: implement an owner-authenticated read-only statement importer for an eligible broker; verify account, currency, contract specs, source digest and execution IDs against genuine provider records; add statement provenance and reconciliation coverage reports; test partial cancels and margin/financing reconciliation; perform prospective out-of-sample evaluation. Never invent unsupported Trading 212 CFD endpoints or enable real orders without explicit owner confirmation and hard risk caps.
