# Loop 5 — disconnected prequential calibration e-process

`frontend/lib/forecast-calibration-eprocess.ts` provides an **offline, read-only, research-only** sequential calibration challenge for a *predeclared* feed, model version, and 1-, 3-, or 12-completed-candle horizon. It neither issues a forecast nor dispatches a notification, paper fill, broker order, or live order.

## Method

For binary upward outcomes `y_t` and recorded prospective probabilities `p_t`, the null hypothesis is **conditional calibration**: `P(y_t=1 | information available when the forecast was issued) = p_t`. Before seeing `y_t`, choose an alternative `q_t = clip((1 + previous_up)/(2 + previous_settled), .01, .99)`, using only outcomes that had settled before this forecast was issued. Update the log e-process by `y_t log(q_t/p_t) + (1-y_t) log((1-q_t)/(1-p_t))`. Under the conditional-calibration null, the product of these one-step likelihood ratios is a nonnegative martingale, even without unconditional independence. Ville's inequality motivates an **anytime research-review** threshold `max(log E_t) >= log(familySize/alpha)` (Bonferroni allocation across a truly predeclared family). This is a challenge to a stringent conditional null, not proof of forecast profitability, drift timing, or broker execution advantage.

The caller must independently pre-register **the complete model/horizon/source family, observation cohort, alpha, and stopping/selection rules** before inspecting outcomes. `familySize` is only caller-declared and is **not authenticated or enforced across invocations**. Post-hoc selection, model retraining on evaluated outcomes, missing negative observations, manipulated timestamps, or undeclared parallel testing invalidate the advertised error-control interpretation. For short cohorts the output is `INSUFFICIENT`. No confidence interval or p-value is claimed. The adaptive alternative is deliberately simple and may have low power against some forms of miscalibration.

## Fail-closed inputs

- Require exact provider, venue, source, instrument, price side, bar duration, model version, and horizon; do not pool different feeds or models.
- Require contiguous, strictly chronological UTC-phase-aligned, non-overlapping target windows. Any missing, pending, voided, duplicate, late, future-dated, malformed, or mixed-source observation throws. Require each earlier target to have settled **before** the next forecast's issue time.
- Require issuance after its base candle close and before the next candle closes; each target settles after its completed close within the caller's declared lag bound.
- Bound evaluation to 500 observations, 30 minimum by default, and a declared `asOf` clock. `asOf` and source/settlement timestamps are caller-supplied and **not independently trusted**.
- Return `REVIEW_ONLY` or `NO_THRESHOLD`, never `BUY`, `SELL`, `LIVE`, or authorization for notification/order execution. Log-space computation avoids numerical overflow; oversized final e-values are censored to `null` rather than infinity.

## Verification

`node --experimental-strip-types --test frontend/tests/forecast-calibration-eprocess.test.ts` (Node 22) and strict TypeScript compilation of the standalone library. Tests are **synthetic**, covering both null-like and strongly miscalibrated fixtures, the 1/3/12 horizons, family threshold, source isolation, gap and duplicate rejection, late/future settlements, prequential information timing, invalid settings, and deterministic replay. Passing tests establish code behavior, not actual market calibration.

## Release gate and Loop 1 handoff

Keep the existing Loop 5 PR **draft**. No merge or Render deployment without reconciled `main`, full exact-head CI, authenticated production workspace, backup restoration, tested rollback, and post-deployment health checks. Loop 1 must supply entitled/authenticated prospective completed candles, server-owned receipt times, immutable issue/settlement records, atomic durable alert outbox, independent delivery receipts, and crash/two-worker recovery before forward use. Historical BID candles are **not executable bid/ask quotes**. Real-money orders remain disabled absent eligible documented broker account, current executable quote, hard risk limits, and explicit owner approval **per order**.

No genuine forward Brier, log loss, net return, expectancy, max drawdown, slippage, financing, or profitability is established by this offline component.
