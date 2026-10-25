# Declared bid/ask execution-friction audit (offline research only)

`frontend/lib/declared-quote-execution-audit.ts` is a disconnected, pure TypeScript reconciliation helper. It accepts a **caller-declared** CFD-like provider/venue/instrument/account/quote-stream scope, declared market-order intents, quote snapshots and fill records. It makes no network requests, does not place or preview executable orders, does not write a database and does not authenticate a broker or archive. **It is not a Trading 212 CFD API integration.**

The caller must explicitly supply the contract's **cash in quote currency per 1.0 price movement per contract**. Never infer contract size from a symbol, merge XAUUSD spot with an unrelated CFD venue, or silently convert currencies. The input quote currency must also be the currency of the cash multiplier and declared commission. Quotes and fills must share exact provider, venue, instrument and batch identities; fills must also match the declared account. The batch SHA-256 is a self-declared identifier, **not** authenticated provenance.

For each matched fill, the audit uses the contemporaneous declared bid/ask quote and computes exact fixed-point one-sided friction relative to the quote midpoint:

- **Half-spread** = `(ask - bid) / 2 × cash multiplier × filled contracts`.
- **Signed slippage** = `(fill - ask) × multiplier × contracts` for BUY, or `(bid - fill) × multiplier × contracts` for SELL. Negative slippage is a declared price improvement.
- **Total friction** = half-spread + signed slippage + declared nonnegative commission. This is **not** a round-trip spread and must not be added to another full-spread estimate. Entry and exit fills each have their own one-sided midpoint reference.

Prices and the cash multiplier are decimal strings with at most six fractional digits; commission is a nonnegative cash decimal with at most two. Results are 13-decimal strings, retaining exact half-microprice precision without floating-point drift. The engine never rounds to a broker settlement unit, infers an FX rate or computes P&L. The user must separately verify broker currency rounding, contract multipliers, and settlement accounting.

The helper rejects crossed/invalid quotes, duplicate IDs, unmatched/unused quote records, orphan fills, overfills, extra schema fields, mismatched identities, future timestamps, fills before order submission, quotes observed after fills, and quotes older than the **caller-declared** maximum age (1–300,000 milliseconds). Timestamps are nonnegative safe-integer **epoch milliseconds**. All records must be bounded to 5,000 each. Multiple partial fills are supported; aggregate complete friction is withheld (`null`) if **any** order remains partially/unfilled or if no fills exist. This is not a substitute for lifecycle accounting of cancellations, rejected orders, amendments, overnight financing or position liquidation.

**Evidence limitations:** A syntactically valid timestamp does not prove when a quote was received. Matching snapshots do not prove a full quote stream, quote executability, fill authenticity, liquidity, trading session, bid/ask at order-routing time, commissions, funding, market impact, slippage distribution or broker suitability. Unused snapshots are rejected to catch inconsistent supplied batches, but this is not a completeness proof. A negative signed friction value can occur under claimed price improvement and is not evidence of a trading edge. Keep the status `SELF_DECLARED_QUOTE_AND_FILL_EVIDENCE_ONLY` until independently retrieved provider/account-specific execution reports, executable quote captures and contract schedules have been verified. Never use this helper to authorize live orders.

Verification (from repository root, Node 22):

```sh
node --experimental-strip-types --test frontend/tests/declared-quote-execution-audit.test.ts
cd frontend && npm test && npm run typecheck && npm run build
```

All included examples are synthetic. No licensed archives, credentials, real market quotes or actual broker fills are distributed.
