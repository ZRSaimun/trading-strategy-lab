# Declared round-trip CFD execution and financing reconciliation (offline)

This is a **research-only** module. It neither contacts a broker nor permits paper or real orders. It does not claim a trading edge, authenticate quotes/fills/financing, verify contract specifications, or validate any archive licence.

## Scope

`backend/app/declared_roundtrip_cost_audit.py` reconciles **all positions and all entry/exit partial fills** declared in a financing population manifest. It re-runs `audit_financing_position_population` for the selected point-in-time cutoff, and **withholds the entire net result** if any declared financing receipt is missing at that cutoff. A caller supplies:

- A financing manifest, its expected SHA-256, financing receipt revisions, and a cutoff already registered in the manifest.
- One position specification per declared position: `position_id`, `direction` (LONG/SHORT), exact-string `quantity`, and exact-string `point_value_cash` (cash per price point per quantity unit).
- An expected SHA-256 from `fingerprint_roundtrip_specs(manifest, specs, financing_sha256)`.
- A bounded population of fill receipts with exact source identity, phase, side, quote ID, bid/ask, fill price, quantity, commission, executed/received/quote timestamps and declared execution statement SHA-256.

**Accounting convention:** All prices multiplied by the caller-declared `point_value_cash` must produce the manifest settlement currency. The module does not convert FX or infer instrument-specific multipliers. Financing receipts use the same currency. No settlement rounding is applied; exact Decimal values are returned as plain strings. These are **not** broker statements or cash-ledger postings.

For each complete position:

```text
gross_mid = direction_sign * (sum(exit_mid * exit_qty) - sum(entry_mid * entry_qty)) * point_value
spread = sum((ask - bid) / 2 * fill_qty * point_value)  # entry and exit
signed_slippage = sum((fill_price - ask) for BUY; (bid - fill_price) for SELL,
                      each multiplied by fill_qty * point_value)
commission = sum(declared_commission_cash)
financing = as-of selected signed financing charges (positive = cost)
net = gross_mid - spread - signed_slippage - commission - financing
    = direction_sign * (sum(exit_fill_price * qty) - sum(entry_fill_price * qty))
      * point_value - commission - financing
```

The exact decomposition prevents double-counting spread when realized fill prices already include the executable side. Signed slippage can be negative for price improvement; it is **not** assumed to be a guaranteed or typical broker fill. Stop gaps, rejects, funding variations, market impact and partial-fill probability are not modeled.

## Fail-closed checks

- No missing, duplicate, extra or cross-source position specifications; caller-provided spec digest must match.
- Every fill must have unique fill ID, declared position/source/instrument/currency, expected phase side, valid quote/statement ID, positive bounded exact decimal prices/quantities and nonnegative commission.
- Quotes must be uncrossed, available at or before execution, and no older than the explicit policy (default 5 seconds). Receipts must have been received by the selected cutoff.
- Reused quote IDs must retain identical source, timestamp and numerical bid/ask; equivalent decimal spellings are accepted.
- Entry and exit fill quantities must each equal the declared position quantity; all entries precede all exits. First entry and last exit must match the declared financing position boundaries.
- Missing financing at the cutoff suppresses **all net outputs**, rather than treating absent charges as zero. Later financing corrections do not rewrite earlier as-of results.
- Finite bounded input lists, strict schemas, integer UTC seconds, order-independent deterministic fill declaration SHA-256, and no file/network writes.

## Testing and limitations

Run from `backend`: `pytest -q tests/test_declared_roundtrip_cost_audit.py`.

Synthetic cases include long/short partial fills, signed slippage, multipliers, fees, quote collisions, chronology, stale/future evidence, duplicate or omitted fills, financing revision vintages, eight distinct synthetic years and ordering invariance. These test software invariants, **not** authentic eight-year market performance.

All statement digests, timestamps, contract multipliers, quantities, fills, commissions and financing schedules are **self-declared**. The module does not prove full market population, genuine brokerage statements, independent preregistration, untouched holdouts, executable quotes, valid bid/ask price sides, broker settlement rounding, source rights or profitability. All execution and verified-profit flags remain `False`. Production deployment requires separate backup restoration, rollback and live health verification.
