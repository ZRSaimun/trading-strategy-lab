# Offline adverse-execution dominance audit (Loop 3)

`backend/app/offline_demo_stress_dominance.py` is an opt-in, disconnected check of the existing `offline_demo_execution_stress.py` research output. It recomputes the original quote-tape digest and the entire adverse stress matrix. It does not contact any broker, access archives, submit orders, or compute returns.

## Invariants and outputs

Each adverse-only scenario must fill no more hypothetical contracts than its baseline. Every hypothetical fill must refer to a unique quote in the original caller-declared tape, remain within that quote's original declared depth, arrive no earlier than its original receipt and no later than the evaluation cutoff, and execute at a price no better than the original executable side plus the declared baseline slippage. It checks exact `Decimal` spread, slippage and commission decomposition, requested-versus-filled quantity, stress-summary consistency and the full-fill cost envelope.

The result reports the minimum hypothetical fill fraction, worst unfilled contract count and all scenarios tied for the worst hypothetical fill count. **It withholds aggregate cost comparison whenever any scenario underfills.** A partial fill with low cash charges is not a low-cost execution of the originally requested quantity.

```python
from app.offline_demo_quote_tape_simulator import fingerprint_demo_quote_tape
from app.offline_demo_stress_dominance import audit_declared_demo_stress_dominance

# Use the simulator's strict scope, intent, quote and adverse-stress schemas.
report = audit_declared_demo_stress_dominance(
    scope, intent, quotes, fingerprint_demo_quote_tape(scope, quotes), stresses,
)
assert report["may_execute_real_order"] is False
assert report["may_execute_demo_order"] is False
```

## Validation and release boundaries

Synthetic regressions include full/partial fills, cancellations, buy/sell pricing, provenance drift, invalid digests, fifteen deliberately corrupted internal results, 250 seeded randomized stress scenarios, deterministic report digests and immutability. Run `cd backend && python -m pytest -q tests/test_offline_demo_stress_dominance.py`, followed by the repository's full CI on the exact PR head.

This is a **consistency audit of self-declared hypothetical data**, not independent authentication, an executable quote, complete liquidity census, broker settlement or source-licensing verification. It cannot establish actual fills, market impact, queue priority, financing, FX, profit, or an untouched multi-year holdout. It is not an order execution gate. Both demo and live execution permissions remain false. Keep this module disconnected from production routes until exact deployment, backup, rollback and independent health checks are verified.
