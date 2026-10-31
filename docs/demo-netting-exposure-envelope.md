# Offline demo NETTING exposure envelope (Loop 3)

`reviewDeclaredDemoNettingEnvelope(scope, manifest, orders, policy)` combines the existing source-bound demo lifecycle and cross-order statement-population validators with a **conservative, declared-only, single-instrument NETTING position envelope**. It is an opt-in research function, not a broker adapter or order execution path.

The caller must declare the account's `positionMode: 'NETTING'`, signed `startingNetContracts`, and `maxAbsContracts` (an offline comparison threshold, **not** an actual broker limit). Each declared BUY fill adds contracts to net inventory; each SELL fill subtracts them. Remaining BUY and SELL quantities on nonterminal orders define the reachable signed interval:

```
net = startingNetContracts + grossBuyFilled - grossSellFilled
minimumReachableNetContracts = net - pendingSellContracts
maximumReachableNetContracts = net + pendingBuyContracts
worstCaseAbsoluteContracts = max(abs(minimum), abs(maximum))
```

`SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, and `CANCEL_PENDING` retain all unfilled contracts as potentially fillable. Neither a cancellation request nor passing an expiry timestamp without an explicit terminal event releases exposure. A confirmed `CANCELED`, `EXPIRED`, `REJECTED`, or `FILLED` event releases remaining order quantity; earlier fills continue to contribute to inventory. This deliberately overestimates reachable risk when orders cannot all fill simultaneously, but it **does not** bound missing external orders or an incorrect starting position.

The status is one of:

- `DECLARED_POPULATION_UNVERIFIABLE`: expected versus observed statement IDs differ. Do not interpret a numerical bound as complete.
- `DECLARED_CAP_EXCEEDED`: the calculated envelope exceeds the caller's declared threshold.
- `WITHIN_DECLARED_CAP_UNVERIFIED`: the supplied records and manifest agree and the *declared* envelope fits the *declared* threshold; **not** broker authentication or approval.

The function rejects unsupported HEDGING mode, malformed/unsafe contract counts, duplicate cross-order IDs, invalid lifecycles, stale quotes, cross-account/source records, and unexpected schema fields. The single-order and statement validators run before any envelope is returned. The manifest, statement hashes, account mode, initial position, and quote evidence remain **caller assertions**; matching hashes/IDs are not proof of complete or authentic broker statements.

This does **not** model cross-instrument portfolio netting, hedged subpositions, margin, contract multipliers, monetary P&L, cash financing, actual order sequencing, slippage, liquidation, or exchange/broker risk reservations. It must never be used to approve a trade. The result always contains `mayExecuteOrder:false`; there are no credentials, network calls, provider API actions, persistence, live/demo orders, licensed data or deploy changes.

Verification: `cd frontend && node --experimental-strip-types --test tests/demo-netting-exposure-envelope.test.ts` and `npm run typecheck`. Tests use synthetic declarations only; real broker evidence and genuine multi-year strategy profitability remain unverified.
