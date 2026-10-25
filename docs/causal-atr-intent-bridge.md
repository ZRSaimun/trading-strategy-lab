# Causal M1 ATR intent bridge — offline research v1

`backend/app/causal_atr_intent_bridge.py` is a **disconnected, deterministic candidate-to-intent compiler** for an *upstream-declared* CRT/ICT liquidity-sweep / MSS-proxy / FVG hypothesis. It does **not** detect or certify any of those events. It produces the exact `frozen-next-open-intent-v1` manifest consumed by the existing `audit_next_open_intents` evaluator, without preregistering an unknowable future next-minute opening price.

## Frozen research convention (not optimized)

Each declared candidate contains `path_id`, `confirmation_close_at` (UTC **close** of the fully completed confirmation candle), `direction` (`LONG`/`SHORT`), the literal hypothesis tag `CRT_ICT_SWEEP_MSS_FVG_CANDIDATE`, and **only** the 15 immediately preceding, strictly contiguous, fully completed M1 OHLC candles. The final candle starts at `confirmation_close_at - 60`. The next hypothetical M1 market entry can be observed only at `confirmation_close_at`, never at signal construction. A higher-timeframe confirmation at e.g. 13:00 UTC must be translated to this exact M1 close convention; do not confuse a candle's open timestamp with its close timestamp.

The fixed `completed-m1-atr14-stop1p5-target3-v1` convention computes 14 true ranges using the prior M1 close, takes their arithmetic mean (ATR-like **simple** average, **not** Wilder-smoothed ATR), and anchors a stop at 1.5 × that range and a target at 3 × that range on opposite sides of the last completed M1 close. Exact `Decimal` arithmetic and deterministic 12-place half-even quantization are used. The stop and target are hypothetical fixed research brackets, **not** validated market-structure invalidation or executable stop orders. The protocol is deliberately fixed rather than selecting multiples after seeing outcomes.

Missing, incomplete or gapped pre-signal minutes are recorded as `PRE_SIGNAL_DATA_GAP`; flat/invalid derived brackets are recorded as `INVALID_PRE_SIGNAL_CONTEXT`. Invalid, nonpositive or malformed OHLC, nonmonotonic clocks, future bars, duplicate candidate IDs/closes, unsupported tags, extra fields and overlarge populations **raise** rather than silently remove an observation. An all-excluded population cannot be published. The resulting downstream evaluator suppresses population means whenever exclusions exist, or any next-open/outcome is unresolved, or the population is insufficient.

The output includes `manifest`, `manifest_sha256`, and `pre_signal_evidence_sha256` binding the supplied pre-signal OHLC and policy. **Neither self-supplied hash proves a historical signal was generated causally or independently timestamped before outcomes.** Store both hashes with independently verifiable pre-outcome time and upstream signal-registration evidence. Candidate detection, full signal-population coverage, source authenticity/licensing/timezone, untouched chronological holdouts, true bid/ask executable quotes, slippage, spread, commission, financing and profitability are **not** verified. Source `price_side` must be explicitly declared; a BID-only archive cannot certify ASK-side execution.

## Integration boundary and tests

Example (Python, from `backend`):

```python
from app.causal_atr_intent_bridge import compile_causal_atr_intents
from app.frozen_next_open_intent import audit_next_open_intents

frozen = compile_causal_atr_intents(source, registered_candidates)
# Persist both hashes externally BEFORE the next M1 open/outcomes.
# Later, after observations arrive and independent source/holdout verification:
review = audit_next_open_intents(
    frozen["manifest"], complete_observations, frozen["manifest_sha256"]
)
```

Use one exact instrument/provider/venue/archive SHA/price-side/horizon source per manifest. Never stitch archives, infer gaps, select only winners, backfill a future opening price into the frozen manifest, or use the output to submit orders. This is a candidate-level adapter for the separate draft [sweep/MSS/FVG research PR #24](https://github.com/ZRSaimun/trading-strategy-lab/pull/24), **not** a production integration with that unmerged TypeScript branch. PR #29 owns independent holdout planning.

Run `python -m pytest -q tests/test_causal_atr_intent_bridge.py` from `backend`; run the complete repository CI (backend, frontend, Docker smoke and free-cloud smoke) before considering a merge. Tests use only synthetic data. No real archive backtest, broker connection, order, paid service, migration, production API route or data mutation is performed.
