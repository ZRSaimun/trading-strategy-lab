# As-of M1 volatility regimes for frozen CRT/ICT intents (offline)

This isolated Python research utility, `backend/app/asof_volatility_regime_audit.py`, labels **pre-signal** volatility compression, normal conditions, or expansion for every eligible `frozen-next-open-intent-v1` trading hypothesis. It is not a live indicator, trade signal, executable quote, performance backtest, or broker integration. It does not change existing research outputs, data, or orders.

## Frozen input contract

Call `audit_asof_volatility_regimes(manifest, expected_manifest_sha256, evidence, expected_evidence_sha256)`. The existing strict manifest validator runs first. The separate `frozen-m1-volatility-evidence-v1` object contains exactly `protocol`, `source`, and `observations`. The `source` object must exactly match the frozen manifest's instrument, provider, venue, archive SHA-256, price side, and horizon. Each observation contains exactly `path_id` and `bars`; every eligible intent must appear **exactly once**, including when its pre-signal history is unavailable (use an empty bar list). Excluded pre-signal signals remain declared in the original manifest and are counted separately.

Each supplied bar contains only `at,open,high,low,close`, using UTC minute-aligned epoch seconds and bounded positive Decimal strings. At most 30 bars may be supplied per intent. Unknown fields, duplicate IDs/timestamps, backward timestamps, invalid OHLC envelopes, nonpositive or malformed prices, post-signal bars and wrong source identities are rejected. Incomplete or gapped 30-minute windows are reported as **UNKNOWN_INCOMPLETE_CONTEXT**, never silently interpolated or dropped.

A frozen signal at `signal_at` refers to the **open of its completed confirmation M1 candle**, whose close is `signal_at + 60`. The most recent permissible context candle opens at `signal_at` and is available only once that candle has completed. The next hypothetical entry candle opens at `signal_at + 60`; it is never supplied to this audit. The caller must not use the report until the confirmation close has occurred.

## Predeclared, non-optimized hypothesis

For exactly 30 contiguous completed M1 bars, compute true ranges `TR_i = max(H_i-L_i, abs(H_i-C_(i-1)), abs(L_i-C_(i-1)))`. Index the 30 bars 0..29. The **baseline** is the average of 14 TRs with bar indices 1..14. The **recent** average uses TR indices 16..29. TR index 15 is deliberately unused so the two 14-TR windows do not overlap.

Use `recent / baseline` to assign one of these **fixed** descriptive labels:

- **COMPRESSION:** ratio ≤ 0.75
- **NORMAL:** 0.75 < ratio < 1.50
- **EXPANSION:** ratio ≥ 1.50

A zero baseline becomes **UNKNOWN_ZERO_BASELINE**. A zero recent range with a positive baseline is labelled compression, but is **not** evidence of executable liquidity. The engine uses Decimal arithmetic and six-place half-even display rounding; threshold comparisons use unrounded ratios. These thresholds are hypotheses chosen in advance, not optimized on historical returns.

## Integrity and interpretation

The two canonical SHA-256 digests are order-independent consistency checks, not proof of externally timestamped preregistration or authenticated vendor data. Preserve the raw licensed archives, source documentation and independently timestamped frozen input hashes outside the evaluator. Every eligible intent remains in the denominator, including unknown contexts; no regime is allowed to remove losing trades after observing outcomes. The report provides complete regime counts and up to 50 bounded examples. It never reports returns, predictive accuracy or broker fills.

The report always sets `source_authenticated=false`, `source_rights_verified=false`, `independent_preregistration_verified=false`, `untouched_holdout_verified=false`, `executable_spreads_verified=false`, `may_exclude_signals=false`, `may_execute_order=false`, and `verified_profitability=false`.

## Verification and next research stage

Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_asof_volatility_regime_audit.py` and the full backend/frontend/Docker/cloud CI before considering any release. Synthetic regression cases cover exact thresholds, data gaps, missing observations, source isolation, digest tampering, future candles, invalid prices and retained exclusions. No private historical ZIPs, authenticated broker bid/ask quotes or untouched holdouts were used to develop this helper.

For future statistical evaluation, preregister the fixed thresholds and complete candidate population **before** holdout observation; compare descriptive regimes only on licensed source-isolated chronological holdouts with week/session clustered uncertainty and explicit spreads, slippage, commission, financing and rollover scenarios. Report all strata, unresolved contexts and exposure overlap. Do not infer profitability or authorize orders from a regime label.
