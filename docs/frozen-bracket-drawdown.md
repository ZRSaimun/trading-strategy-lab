# Frozen M1 bracket downside-path stress (Loop 2, offline)

`backend/app/frozen_bracket_drawdown.py` extends the already merged `frozen_bracket_population` / `ohlc_bracket_uncertainty` auditors. It is disconnected research code: **no strategy optimizer, network request, database import, broker adapter, execution endpoint or live trading signal**.

## Purpose and interpretation

A frozen, externally retained manifest binds the source, eligible population, declared exclusions, direction, entry, stop, target and horizon **before** inspecting outcomes. The existing audit validates the manifest digest, exact membership and source, then bounds completed-M1 bracket outcomes. This module sorts those validated outcomes chronologically and evaluates the maximum possible peak-to-trough loss of the **additive-R** path under the four predeclared *additional* round-trip notional-price cost assumptions: 0, 5, 10 and 20 bps.

For trade *i*, let its bounded net return be `[L_i,U_i]`. For every candidate peak-to-trough interval, the largest possible decline occurs when every return in that interval is its lower bound. Therefore the maximum drawdown over all possible interval-level intraminute resolutions equals the maximum drawdown of the sequence of `L_i`. This is an adverse uncertainty envelope, not a prediction. The all-upper sequence's drawdown is shown only as a comparator; it **is not** the minimum feasible drawdown. Results use exact Decimal arithmetic, not float rounding.

A censored outcome, any declared pre-signal exclusion, fewer than 30 eligible signals, or fewer than 12 active UTC weeks **withholds all drawdown metrics**; no survivor-only result is substituted. A SHA-256 digest supplied by the caller does not independently prove that it was recorded before outcomes, or that the upstream generator registered all eligible signals. No compounding, overlapping-trade portfolio exposure, margin, sizing, real spread, funding, slippage, broker fill or execution model is represented. Adding per-trade R units is not a monetary equity curve. Never claim a profitable edge from these synthetic tests or use optimistic bounds to justify orders.

## Run tests

```bash
cd backend
PYTHONPATH=. python -m pytest -q tests/test_frozen_bracket_drawdown.py
```

## Handoff

PR #24: retain causally frozen CRT/ICT signal registry, rather than reconstructing it after outcomes. PR #29: independently certify chronological holdout and embargo; this module does not do so. PRs #41/#43: archive rights, actual source provenance, timestamp uniqueness and executable BID/ASK remain unresolved; never promote quarantined archives from these metrics. PR #25: broker-specific paper-fill reconciliation remains separate. Do not commit raw licensed prices, private digests, credentials or live orders.
