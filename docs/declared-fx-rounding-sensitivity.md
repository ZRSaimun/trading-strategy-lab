# Declared-only FX cash rounding sensitivity (offline)

`backend/app/declared_fx_rounding_sensitivity.py` extends the merged CFD FX conversion audit without changing existing routes, order execution, storage, or provider connections. It **reruns** upstream cost/financing/FX checks; it does not trust caller-supplied net P&L.

Freeze a policy using `fingerprint_fx_rounding_policy(fx_policy_sha, cutoff, {"reporting_minor_units": 2, "rounding_mode": "HALF_EVEN"})`. Supported modes: `HALF_EVEN`, `HALF_UP` (ties away from zero), and `TOWARD_ZERO`; 0–6 minor units. Supply the matching digest and upstream audit inputs to `audit_declared_fx_rounding(...)`.

The result compares **rounding each closed position before summation** with **summing unrounded positions before rounding once**. It reports per-position rounding deltas and the difference between conventions. Missing upstream FX/financing withholds net output. Invalid policy, altered digest, inconsistent source/cutoff, duplicate or missing positions, malformed cash, and aggregate mismatches fail closed. Synthetic tests cover positive/negative ties, determinism, and 256-position conservation.

**Limitations:** These are hypothetical sensitivity scenarios, **not actual broker settlement conventions**. No fill-level or fee-level rounding, multi-currency ledger, broker contract terms, tax, executable FX liquidity, source authentication, independent holdout, or verified trading profit. Minor units are caller-declared rather than inferred from currency codes. A hash does not prove pre-outcome registration. Trading permissions remain false; no real/demo orders, broker calls, paid services, licensed archive publication or production writes.

Test: `cd backend && pytest -q tests/test_declared_fx_rounding_sensitivity.py`.
