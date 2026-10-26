# Offline adverse execution sensitivity census (Loop 3)

`backend/app/offline_demo_execution_stress.py` is an additive, disconnected research-only companion to the existing `offline_demo_quote_tape_simulator.py`. It **does not** fetch data, authenticate a broker, submit a demo/live order, read archives, change stored data, or calculate profitability.

## What it checks

For one caller-declared source/account/instrument, order and original quote tape, the module **first** reruns the existing exact-digest baseline simulation. It then runs 1–8 explicitly declared adverse scenarios. Each stress can widen bid/ask symmetrically (preserving the declared midpoint), increase adverse slippage, reduce per-quote declared depth, and delay quote delivery. A delayed quote beyond the original as-of cutoff is unavailable in that hypothetical scenario; expiry, cancellation and maximum quote-age rules remain unchanged. Each derived tape is separately SHA-256 fingerprinted.

Inputs use exact bounded decimal strings; no binary-float money calculations. Stresses must be genuinely adverse, use a strict schema, and may never improve the quote, slippage, depth or latency assumptions. Unknown, malformed, duplicated or excessive stress specifications fail closed. Source identity is inherited from the baseline and never rewritten. Original inputs are not mutated.

The result reports **both** hypothetical fill quantity and entry-side cash costs. It intentionally withholds `worst_comparable_full_fill_entry_cost_cash` unless the baseline **and every stress** fill the entire requested quantity. This prevents a no-fill scenario with zero recorded entry cost from being misrepresented as a cheap execution. Results are deterministic and explicitly marked as hypothetical.

## Example

```python
from app.offline_demo_quote_tape_simulator import fingerprint_demo_quote_tape
from app.offline_demo_execution_stress import audit_declared_demo_execution_stress

# scope, intent, quotes are the existing simulator's strict dictionaries.
digest = fingerprint_demo_quote_tape(scope, quotes)
result = audit_declared_demo_execution_stress(scope, intent, quotes, digest, [
    {
        "name": "adverse_depth",
        "spread_widen_price": "0.2",
        "extra_adverse_slippage_price": "0.25",
        "depth_percent": 40,
        "quote_delivery_delay_ms": 120,
    },
])
assert result["may_execute_real_order"] is False
```

## Verification and limitations

Run `cd backend && python -m pytest -q tests/test_offline_demo_execution_stress.py` and the full repository CI. Synthetic tests cover bid/ask side selection, limit prices, cancellation races, quote-age rejection, time-cutoff omission, partial depth, exact cash arithmetic, malformed source/stress data, immutability, hash determinism and randomized quantity invariants.

**Important:** A declared quote is not proof of executable liquidity. A hash is not a trusted timestamp or authenticated broker receipt. The scenario is *entry-side only*: it does not model queue position, market impact, exits, overnight CFD financing, swap/borrow charges, funding changes, settlement FX, liquidation, broker margin, gaps, or strategy P&L. No real market performance, untouched holdout, independently registered stress plan, or profitable edge is demonstrated. A real broker adapter would require separately authenticated read-only receipts and explicit order safety controls. This module provides no such adapter or permission.
