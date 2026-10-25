# Declared CFD cost envelope (offline research only)

`reviewDeclaredCfdCostEnvelope` combines **revalidated, self-declared** quote/fill friction with signed CFD financing cash charges **only when both evidence sets are complete**. It rejects provider, venue, instrument, account or currency mismatches and unexpected stress fields. A partial/unfilled order, missing rollover receipt or empty rollover schedule produces `null` base and scenario costs; it never substitutes zero.

The one-sided quote friction already contains half-spread, side-specific slippage and commission. Stress inputs are **incremental** half-spread, adverse slippage, commission and financing in the **same currency**, in exact cents, and must not re-add existing costs. The declared budget is an illustrative **cost tolerance**, not a loss cap.

All aggregation is fixed-point BigInt, retaining 13 decimal places for quote friction and signed financing credits. A negative total can reflect declared favorable slippage or financing credits; it is **not profit**. There are no strategy outcomes, real broker connections, live orders, network calls, market-data reads or database writes.

**Critical limits:** Neither input audit authenticates quotes, fills, contract multipliers, the financing calendar or statement completeness. Matching caller-provided source IDs and hashes does not authenticate identities. The combined envelope is **not** an executable spread estimate, risk limit, broker-validated result, trading edge or proof of profitability. Independently verify authorized source data and broker terms before evaluating a frozen strategy. Never use this module to authorize live orders.

Run isolated tests from `frontend`: `node --experimental-strip-types --test tests/declared-cfd-cost-envelope.test.ts` (Node 22).

## Temporal cross-audit guard

Before combining costs, the envelope rejects quote evidence whose `asOf` predates the declared financing position close, orders submitted after that close, and fills outside the inclusive declared `[openedAt, closedAt]` position window. Orders submitted before opening are allowed if their fills fall within the interval. These checks run after the underlying quote/fill and financing audits; they prevent obvious cross-period mixing, not cross-position mixing. Order and fill records carry no authenticated `positionId`, so same-account orders from another position **can still be mixed** if their timestamps overlap. A production-grade cost attribution requires independently authenticated position/order/fill linkage and verified broker timestamps. The new isolated seven-case synthetic test suite and three end-to-end envelope regression tests exercise this guard.
