# Frozen cost capacity — offline descriptive research only

`backend/app/frozen_cost_capacity.py` provides a conservative **additional-cost sensitivity** summary for a complete frozen M1 bracket population. It does **not** identify a profitable strategy, estimate an executable CFD quote, or authorize orders.

## Protocol

Call `audit_frozen_cost_capacity(manifest, paths, expected_manifest_sha256)`. The existing `audit_frozen_bracket_population` gate first checks the exact frozen manifest SHA-256, immutable source identity, signal-to-path membership, next-minute entry timing, bracket identity, and OHLC outcome bounds. This tool never discards losing or intrabar-ambiguous paths.

When the full population is eligible for descriptive statistics (at least 30 paths, at least 12 active UTC weeks, zero declared exclusions, zero censored outcomes), it reports:

- Sum of lower and upper **gross R bounds** across all eligible signals.
- The **additional notional cost sensitivity**, in total R lost for each additional 1 basis point of round-trip notional cost, computed as `sum(abs(entry)/(10000 * abs(entry-stop)))`. This is a model sensitivity, **not** a broker spread.
- The descriptive additional-cost-to-zero threshold separately for lower and upper population R bounds: `gross_bound / total_cost_sensitivity` if and only if the gross bound is positive. Each threshold is **floored** to six decimal places, never rounded upward. A null threshold means that bound is already nonpositive at zero extra cost. This is interpolation under the existing linear cost assumption, not an observed broker quote or a safe trading budget.
- Lower and upper additive net R totals for the existing frozen **0/5/10/20 bps** additional round-trip scenarios, with descriptive flags for lower-bound positive, upper-bound nonpositive and zero crossing.
- The largest **tested** bps value with positive lower bound and the first **tested** bps value with nonpositive upper bound. Untested cost scenarios are not claimed as validated.

The thresholds describe the zero crossing of a *sample additive R bound*, not the probability of a profitable next trade. There is no statistical inference, out-of-sample calibration, independence adjustment, portfolio netting, spread forecast, slippage, financing, margin, exchange fees or order execution model.

## Fail-closed behavior

All return statistics are withheld for incomplete, censored, excluded or insufficiently dispersed populations. Duplicate or missing signal paths, changed source identity, changed frozen bracket/entry clocks and manifest digest mismatch are rejected by the upstream gate. This helper additionally rejects missing/invalid net-R bounds, unexpected scenario identity and materially inconsistent linear-cost arithmetic.

The upstream evaluator uses a 50-digit Decimal context; this helper uses 80 digits for sums and cost sensitivity, with a narrow tolerance solely for upstream finite-precision rounding. Outputs are descriptive decimal values, not a claim of mathematically exact rational fractions.

A caller-supplied matching manifest SHA-256 **cannot** independently prove that the signal population was preregistered, that source archives are complete and licensed, that timestamps are valid UTC, or that the test interval was untouched. The available HistData BID-only archives remain quarantined until collisions, provenance, rights and realistic bid/ask costs are verified.

## Verification and release scope

Run `cd backend && pytest -q tests/test_frozen_cost_capacity.py`, then complete backend/frontend/PostgreSQL/Docker/cloud CI before merging. Synthetic tests cover winning, losing, ambiguous, SHORT and negative-price paths; scenario arithmetic; six-decimal downward flooring; canonical input order; censored/excluded/insufficient samples; source and digest tampering; and malformed inputs.

The module is offline, additive, read-only and disconnected from the API, UI, database, broker adapters and live trading. It should be evaluated against **independently authenticated, untouched chronological holdouts** only after a documented data-quality and licensing review. No user-facing Render deployment is required for this offline utility.
