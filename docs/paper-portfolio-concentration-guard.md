# Loop 4: disconnected PAPER portfolio concentration preflight

This isolated Python module evaluates **hypothetical, caller-declared** gross portfolio exposure before considering another paper position. It does not read or update the database, authenticate market data, connect to a broker, approve an order, or expose an API endpoint.

`backend/app/paper_portfolio_concentration_guard.py` exports `evaluate_portfolio_concentration(snapshot, now_ms=trusted_server_clock_ms)`. Use string-valued, nonnegative, bounded plain decimals for money and policy inputs. The input has one candidate and up to 50 existing positions. Every position must declare positive gross notional, margin and stressed loss; missing exposure cannot silently become zero. All amounts must already be converted to the declared account currency by an **independently verified** process, which this module does not provide.

The guard calculates:

- Aggregate **gross** notional, including opposing BUY and SELL exposures without hedge/netting credit.
- Per-symbol and per-risk-group gross concentration, including the proposed candidate.
- Aggregate stress loss and per-group stress loss, multiplied by an owner-declared conservative correlated-shock factor from 1 to 5.
- Proposed-position stress, account-wide stress budget, equity remaining after stress, reserved margin, and gross leverage.
- Inventory and every quote's chronological order, <=3-second observation age, and <=1-second transport delay.
- Duplicate position IDs, missing/incomplete declared inventory, unsupported Trading 212 CFD API mode, inconsistent policy ceilings, and excessive declared leverage policy (>5x).

The output includes check-by-check diagnostics, exact decimal summaries and a deterministic SHA-256 diagnostic fingerprint. **It always returns `status=HOLD_RECONCILIATION`, `may_execute_paper_order=false` and `may_execute_real_order=false`, even when all structural checks pass.** The fingerprint is not an approval signature or replay-prevention token.

## Usage

From `backend/`:

```bash
PYTHONPATH=. python -m pytest -q tests/test_paper_portfolio_concentration_guard.py
```

Build a complete input using the exact keys defined in `ROOT`, `LIMITS`, and `POSITION`. Do not supply live credentials, personal information, or customer account numbers as aliases. Pass a trusted server clock, not client time.

## Integration and release gates

This is **not** a broker position reconciliation or a guarantee of maximum losses. Risk groups are manually declared and may miss correlated exposure. A stress multiplier is not a market-wide worst-case bound; gap risk, stop failure, FX conversion, liquidity, fees, and changing margin schedules can exceed estimates. Quote timestamps and `inventory_complete` are not authenticated. All assumed equity, gross notional, existing positions, margin, and risk group mappings must eventually come from verified provider inventory and conversion metadata.

Before any paper workflow may rely on these results, atomically bind authenticated positions, pending orders, quote source, protective-stop receipts, risk-policy revision, emergency kill-switch state, durable risk reservations, and journal history to the same server-side transaction. Reject uncertain broker outcomes, stale sessions, duplicate attempts, and concurrent writers. A passing diagnostic must never override those checks.

Before any **real-money** order, require a separately secured supported provider account and fresh, positive owner confirmation for the **specific** order. No live order submission is implemented or authorized by this module.

Trading 212's official Public API is documented for **Invest and Stocks ISA**, not CFD accounts. Its order submission is non-idempotent; do not retry unknown outcomes. Official references:

- https://docs.trading212.com/api/section/general-information/api-limitations
- https://docs.trading212.com/api/orders/placelimitorder

No paid calls, secrets, production writes, migration or deployment are required for this preflight.
