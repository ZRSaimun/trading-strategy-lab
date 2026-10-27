# Exploratory observed-only 0–5 bps cost crossing (Loop 2)

Run from `backend/`:

```bash
python -m app.offline_sweep_aggregate_cost_crossing ../docs/offline-sweep-32-archive-confluence-aggregate-20261027.json
pytest -q tests/test_offline_sweep_aggregate_cost_crossing.py
```

The disconnected auditor first runs `offline_sweep_aggregate_audit.audit_aggregate`, which reconciles the **fixed eight** FVG / MSS-like / displacement states, all counts, 5-decimal means and the explicit no-holdout/no-order/no-profit claims. It then computes a **descriptive observed-only** crossing of the mean net R between the *declared* additional **0 and 5 basis-point** cost scenarios, if and only if the zero-cost observed mean is strictly positive and the +5-bps mean is strictly negative. No costs are extrapolated outside this interval. Empty states, already-nonpositive states and non-crossing states return null thresholds.

For a positive 0-bps mean `a` and negative 5-bps mean `b`, the interpolated additional cost at which the **observed-only** mean reaches zero is `5*a/(a-b)` bps. Since the eight reported cell means were independently rounded to five decimals, each endpoint can vary by at most half a last decimal place (`0.000005 R`). Evaluating both endpoints at their lower and upper rounding bounds gives a conservative interval, rounded outward to eight decimals. Weighted overall endpoints are computed from **all eight fixed cells**, not by selecting winners. These bounds cover only *decimal rounding*, not sampling, missing outcomes, price errors, execution costs or model uncertainty.

For the previously inspected 16 annual exploratory later-period slices, 2,043 observed trades have reconstructed observed-only mean approximately **+0.00731388 R at 0 additional bps** and **−0.30760623 R at +5 additional bps**. The resulting **observed-only interpolated crossing is about +0.11612273 additional bps**. This small hypothetical tolerance demonstrates cost fragility of the *observed subset*, **not** a profitable strategy, actual spread estimate, safe cost allowance, or return prediction. The **244 entered positions with unknown exits remain unknown**, and 40 confirmed signals have unobservable entries. The retrospectively inspected six-trade positive all-three confluence state has no observed-only crossing within 0–5 bps, but is too sparse and selected after inspection; it is **not a candidate approved for release**.

## Scope and prohibitions

- The input is a declared aggregate from an independent float/Pandas reproduction, **not** a rerun of the committed Decimal trade engine, an authenticated source, an independently protected holdout, or a broker BID/ASK execution receipt.
- All costs are **illustrative extra round-trip bps**. No spread, commission, financing, market impact or FX-conversion evidence is verified.
- A linear crossing of rounded aggregate returns cannot supply a confidence interval, explain unknown exits, validate fillability, overcome multiple comparisons, or authorize a trading signal.
- Read-only CLI and pure functions: no archive writes, network calls, broker connections, paper/live orders, account mutations or production changes. `verified_profitability` and `may_execute_order` are always false.
- Release remains blocked pending independently verified backups/restoration, rollback, health checks, owner-confirmed hosting workspace, authenticated data rights and a prospective frozen protocol.
