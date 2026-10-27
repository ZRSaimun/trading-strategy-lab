# Loop 2: aggregate-only unknown-exit net-R tipping points

This disconnected read-only calculation applies to the **already inspected** 16 annual exploratory later-period slices in the eight-state confluence report. It first invokes `offline_sweep_aggregate_audit.audit_aggregate` to reject malformed counts, invented empty-cell means, invalid cost arithmetic and unsupported holdout/profit/order claims.

For each confluence state and the full entered population, it solves the identity:

`observed_count × observed_mean_net_R + unknown_count × required_unknown_mean_net_R = 0`.

The required unknown mean is a **net realized R** under the same illustrative 0 or +5 bps scenario, **including** costs attributable to the unknown exits. Because unknown exits have no observed fills or costs, this is a conditional algebraic threshold, not an estimate, a broker-executable break-even, or a valid imputation. With zero unknown exits, the threshold is explicitly null.

The published cell means were rounded to five decimal places. The auditor reports a conservative interval by allowing each cell mean to vary by ±0.000005R; displayed thresholds are rounded to eight decimal places. The interval reflects only **rounding uncertainty**, not statistical uncertainty, unknown fills, source authenticity or market risk.

The full population includes **2,043 observed and 244 censored entered positions**. At illustrative additional +5 bps, the rounded observed-only mean is approximately **−0.30761R**; the 244 unknown exits would need to average approximately **+2.576 net R** to offset the observed aggregate loss. This does not imply they could or did achieve that. The six-trade retrospective FVG+MSS-proxy+displacement cell has zero censored exits, so no unknown-exit rescue applies there. The already-inspected positive cell is not a selectable, independently validated trading edge.

Run from `backend/`:

```sh
PYTHONPATH=. python -m app.offline_sweep_aggregate_censor_tipping ../docs/offline-sweep-32-archive-confluence-aggregate-20261027.json
PYTHONPATH=. python -m pytest -q tests/test_offline_sweep_aggregate_censor_tipping.py
```

No new archives are read, no trade-level Decimal engine parity is established, and no protected prospective holdout, executable BID/ASK, financing receipt or data-rights proof is provided. This module is not imported by a production API, signal, broker adapter or order path. **No deployment or real-money execution authorization.**
