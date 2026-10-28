# Loop 2: independent 32-archive confluence census (27 October 2026)

**Status: exploratory research only — NOT an independent holdout, broker backtest, verified edge, trading signal, or release approval.** No raw licensed candles, archive hashes, credentials or proprietary source files are included in this document.

## Scope and method

A separate, read-only local **floating-point/Pandas reproduction**, not execution of the committed Decimal engine, inspected 32 owner-supplied HistData-named ASCII M1 ZIP archives: 16 annual archives (NSXUSD 2016–2025, XAUUSD 2022–2025, WTIUSD 2022–2023) and 16 separately analyzed partial/monthly 2026 archives. It processed **5,772,161 M1 rows** into **373,253 complete source-local M15 bars**. The source clock/timezone, provenance, redistribution rights, BID/ASK side and broker-executable costs have not been independently authenticated.

Frozen v3 reproduction: prior 16 complete M15 bars; sweep/reclaim; next completed confirmation; following-open hypothetical entry; 2R target, stop-first same-bar ambiguity, adverse source-open stop proxy, 16-bar holding horizon, conservative non-overlap for censored entries, per-archive chronological 70/30 *exploratory* split and 16-bar embargo. No parameter search, strategy change or candidate filtering was performed. Illustrative **additional** 0/5/10/20 bps round-trip costs are converted to R by each observed trade's original entry/stop distance. Missing entries, invalid geometry and entered-but-censored exits are not assigned invented outcomes.

The eight pre-entry diagnostic states combine: completed-confirmation same-direction three-candle FVG, completed-confirmation close beyond the prior 16-bar range (minimal MSS-like proxy), and completed-confirmation directional body >= prior-16 median full candle range (minimal displacement proxy). These are not complete institutional ICT detections. The state is fixed before hypothetical entry and exit.

## Population reconciliation

| Scope | Confirmed | Entered | Observed exits | Censored entered | Entry unobservable | Invalid geometry |
|---|---:|---:|---:|---:|---:|---:|
| 16 annual later slices | 2,327 | 2,287 | 2,043 | 244 | 40 | 0 |
| 16 partial/monthly 2026 later slices | 192 | 186 | 160 | 26 | 6 | 0 |

The 16 annual later-slice population exactly reproduces the earlier independent v3 census (2,327 / 2,287 / 2,043 / 244 / 40). The 2026 population also reconciles to the previously recorded 192 / 186 / 160 / 26 / 6. This is an **independent local arithmetic consistency check**, not parity verification against the repository's Decimal module or evidence of independent test-set performance.

## Annual later-slice eight-state census

All 16 annual later slices have been previously inspected. Reported means include **observed exits only**; censored entered outcomes remain unknown.

| FVG/MSS/Displacement state | Confirmed | Entered | Observed | Censored | Missing entry | Mean R, +0 bps | Mean R, +5 bps |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 / 0 / 0 | 1,442 | 1,415 | 1,243 | 172 | 27 | +0.00866 | −0.37529 |
| 0 / 0 / 1 | 732 | 725 | 669 | 56 | 7 | −0.00034 | −0.21662 |
| 0 / 1 / 0 | 0 | 0 | 0 | 0 | 0 | undefined | undefined |
| 0 / 1 / 1 | 54 | 54 | 50 | 4 | 0 | +0.04760 | −0.06914 |
| 1 / 0 / 0 | 69 | 63 | 54 | 9 | 6 | +0.00018 | −0.22898 |
| 1 / 0 / 1 | 24 | 24 | 21 | 3 | 0 | −0.12735 | −0.25779 |
| 1 / 1 / 0 | 0 | 0 | 0 | 0 | 0 | undefined | undefined |
| 1 / 1 / 1 | 6 | 6 | 6 | 0 | 0 | +0.78166 | +0.70004 |
| **Total** | **2,327** | **2,287** | **2,043** | **244** | **40** | — | **−0.30760** |

For the six annual later-slice observed 1/1/1 outcomes, the *observed-only* illustrative mean R is +0.78166 / +0.70004 / +0.61841 / +0.45516 at 0 / 5 / 10 / 20 additional bps, respectively. **This is only six retrospectively inspected trades (6/2,043 observed), not a usable performance estimate.** Eight joint states, other inspected diagnostics, small samples, unknown missing exits, possible dependency and repeated inspection create substantial selection/overfitting risk. Do not promote this cell to a candidate, live signal, risk gate, or profitability claim.

Across all 16 annual later slices, the unchanged *whole-cohort* observed-only mean is approximately **−0.30760R at +5 bps**. The earlier finding that all 16 annual later-slice per-archive observed-only +5-bps means were negative is unchanged.

## Separately inspected 2026 partial/monthly later slices

The 1/1/1 joint state had **one confirmed/entered/observed outcome** and an illustrative +5-bps return of +0.35502R. The full 2026 later-slice population had **160 observed, 26 censored entered**, with observed-only mean **−0.30148R at +5 bps**. These are tiny, non-independent, often incomplete periods and do not rescue or validate any hypothesis.

## Research decision and boundaries

1. **Do not select, optimize, rank or enable the rare 1/1/1 combination** using these already-inspected archives. Freeze hypotheses and data provenance first; require independently protected prospective observations and realistic executable broker costs before any inference.
2. A positive subgroup mean does not negate the negative full-population exploratory result. Unknown exits and admission-path changes invalidate a naive subgroup-only portfolio replay.
3. This reproduction uses floating-point arithmetic, and is **not** a rerun of the committed Decimal engine. Exact Decimal-module private-archive replay and independently checked source/clock/BID-ASK/financing receipts remain outstanding.
4. Keep PR #136 **draft / unmerged / undeployed**. Production restore/rollback/health safeguards and owner-confirmed hosting workspace remain unverified. No order submission, paid service, production database change or broker permission is authorized by this document.

**Coordination:** Loop 3 / holdout integrity should treat all eight cells as inspected development hypotheses, not untouched holdout evidence. Loop 4 / paper risk must not use the six positive 1/1/1 observations to loosen risk or order gates. Loop 1 / provenance should preserve source/clock/side validation requirements.
