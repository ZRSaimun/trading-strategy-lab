# Loop 2: declared confluence attrition and cost-drag census (read-only)

This standalone standard-library command consumes only the previously published
**rounded, unauthenticated, exploratory** eight-cell aggregate. It runs the
closed-schema arithmetic auditor first, then reports every confluence cell
without retrospective filtering or new trade selection.

From `backend/`:

```sh
PYTHONPATH=. python -m app.offline_sweep_aggregate_attrition ../docs/offline-sweep-32-archive-confluence-aggregate-20261027.json
PYTHONPATH=. python -m pytest -q tests/test_offline_sweep_aggregate_attrition.py
```

## Interpretation and arithmetic

The observed/entered, unknown-exit/entered, missing-entry/confirmed and
observed/all-observed percentages are descriptive ratios rounded to four
decimal places; a zero denominator produces `null`, never a manufactured 0%.
The cost-drag measure is **sum of observed net R at 0 additional bps minus
sum of observed net R at 5 additional bps**, derived from rounded per-cell
means. It is not a quote, actual spread, financing cost, or executed P&L.

Each reported five-decimal mean may differ from its unrounded counterpart by
at most 0.000005R. An observed cell with `n` outcomes therefore has a
conservative total-net-R enclosure of `n × 0.000005R` around the reconstructed
sum. The **difference of two independently rounded** means has a conservative
cost-drag enclosure of `n × 0.000010R`. Lower endpoints are rounded outward
down and upper endpoints outward up to eight decimal places. These are only
**arithmetic rounding enclosures**, not confidence intervals, source error
bounds, model risk estimates or trading-risk limits.

The previously inspected 16 annual exploratory later-period slices contain
2,327 confirmed signals, 2,287 entered positions, 2,043 observed exits and
244 entered positions with **unknown** exits (10.6690% of entered). Another 40
confirmed signals have missing entry observations. The reconstructed
observed-only 0-bps net total is +14.94225R; at illustrative extra 5 bps it is
-628.43952R. The observed-only illustrative 0-to-5-bps drag is +643.38177R,
**not** an actual broker charge. The retrospectively positive FVG+MSS-proxy+
displacement cell contains only six observed exits (0.2937% of the observed
population) and cannot justify selection or a profit claim.

No unknown exit is filled or assigned an outcome. No new historical archive,
source clock, Decimal trade-engine replay, independent holdout or executable
BID/ASK cost receipt was examined. No private ZIP, candle, credential or order
is published or submitted. This module is disconnected from production API,
scheduler, signal, database, broker and deployment paths.

Keep PR #136 **draft, unmerged and undeployed** until independent production
backup restore, rollback, health-check and hosting ownership evidence is
verified. This offline census does not authorize live trading.
