# Paper CFD financing and cashflow reconciliation (research-only)

`frontend/lib/paper-cashflow-reconciliation.ts` provides a pure, read-only reconciliation step for a **closed** simulated order from the separate bid/ask `PaperExecutionLedger` in PR #18. It does not connect to a broker, calculate an overnight rate, infer exchange calendars, create an order, update a database or change the order itself.

Supply the original exact instrument/provider/venue identity, closed paper order, a Unix-second settlement cutoff (`asOf`) and explicitly sourced cashflow entries. Supported entries are overnight financing, borrow fees, FX conversion and broker adjustments. Each has a unique ID, the exact source identity, posted time, signed currency amount and a human-readable reference. Negative values are charges; positive values are credits. The same ID with identical contents is idempotent, conflicting duplicates fail, and entries dated before paper entry or after `asOf` fail. Fees posted after paper exit can be included only when the caller advances the settlement cutoff; they cannot silently appear in an earlier report.

The reconciler recomputes the underlying simulated BUY/SELL price P&L using the supplied contract point value, verifies the round-trip commission against the recorded per-side commission rate and units (not merely against the caller-supplied total), verifies commission-inclusive P&L, and adds the explicitly provided cashflows. It also requires positive entry/exit prices, an explicit BUY/SELL side, observed and received fill timestamps, a post-submission entry, a post-entry exit and a settlement cutoff no earlier than the exit. It rejects identity mismatches, tampered base P&L, impossible timestamps and non-finite/overflowed values. The original paper order and all input cashflows remain unchanged.

**Important limitations:** `knownCashflowAdjustedPnlCurrency` is NOT independently verified broker net P&L. `coverage: PARTIAL_UNVERIFIED` is always returned because missing cashflows, provider contract rules, weekends/triple-swap, financing rates, margin liquidations, borrow fees, taxes and FX may remain unknown. An empty cashflow list is *unknown coverage*, not proof of zero charges. The posted source/reference strings are declarations and do not authenticate a broker statement. This module does not establish a profitable strategy or bound gap risk. The next phase must use broker-authenticated settlement data, a durable journal, verified contract units and broker demo-fill comparisons.

## Verification

```sh
cd frontend
node --experimental-strip-types --test tests/paper-cashflow-reconciliation.test.ts
tsc --noEmit --target es2022 --module nodenext --moduleResolution nodenext --allowImportingTsExtensions --skipLibCheck lib/paper-execution.ts lib/paper-cashflow-reconciliation.ts
```

Twelve synthetic regression tests cover financing and FX debits, credits posted after closure, duplicate IDs, source/time validation, forged commission and P&L pairs, impossible fill chronology, invalid prices/sides, absent-charge warnings and arithmetic overflow. A saved paper order and declared provider metadata remain unauthenticated; passing this reconciliation is not proof of a broker statement or genuine fill. No live or historical broker profitability is measured.
