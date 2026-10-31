# Exploratory source-wall M1 CRT/ICT confluence cost sensitivity

The standalone offline Python module app.offline_m1_cost_sensitivity.audit_histdata_ascii_zip is a **read-only, non-executing** research diagnostic for an owner-provided original HistData ASCII M1 ZIP. It does not import prices into the app, connect to a vendor, database, broker, paid service or deployment. It reads a bounded single CSV member without extraction, hashes the original compressed bytes before and after reading, and emits aggregate counts and research fingerprints. ZIP CRC is checked when the CSV is fully read. No licensed archive or individual OHLC prices are committed.

## Frozen illustrative rule, not a verified trading strategy

1. At completed M1 candle i, sweep the preceding 20 contiguous candles' high or low and close back inside that prior range. Double-sided sweeps are ambiguous and excluded.
2. Within the following five completed candles, confirm a same-direction close beyond the previous three candles' high/low (MSS proxy), plus a three-candle wick FVG: low[i] > high[i-2] for long, reverse for short. Multiple competing sweep origins at one close are excluded.
3. Hypothetical entry is the **next contiguous candle open** after confirmation, never the confirmation close. Exit is the close of the 15th contiguous M1 candle counting the entry candle. Missing minutes, DST-backward jumps and duplicate wall timestamps reset warmup; any gap across entry-to-exit censors the outcome. Overlapping entries are excluded in first eligible signal order.
4. Signed price change is expressed in basis points, with **illustrative flat round-trip costs** of 0, 5, 10 and 20 bps deducted. No executable BID/ASK, spread, commission, slippage, swap/financing, market impact, contract size, order acceptance, stop-loss or live quote is modeled. The 70/30 split is purely descriptive by evaluated signal order, **not an untouched holdout**. No parameters were optimized in this run.

The parser treats timestamps as **unverified source-wall-clock minutes**. It does not assert UTC or correct DST, authenticate HistData origin or licensing, or establish a complete trading calendar. The price side is UNVERIFIED_SINGLE_SIDE. All outputs explicitly deny broker/trade authorization, protected-holdout status and verified profitability. This diagnostic is distinct from the main causal_m1_confluence_detector and its independent source-lineage requirements; similar rules do not prove identical full-system acceptance.

## Owner-provided archive replay, 29 October 2026 (exploratory only)

| Original ZIP identity | Bars | Nonoverlap evaluated | Mean gross bps | Mean after illustrative 5 bps | Mean after illustrative 10 bps | Later 30% after 5 bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NSXUSD 2025, SHA-256 865006539b7a3abe6ce3742e17604e5bf003b89583b349228570d343f78ae16f | 340,553 | 3,783 | +0.137280 | -4.862720 | -9.862720 | -4.893691 |
| WTIUSD 2022, SHA-256 876d8e31b1334a5c32d490af8773cdf33c83cade33ff477d46348f3d25553468 | 354,224 | 3,450 | -0.285862 | -5.285862 | -10.285862 | -5.765629 |
| XAUUSD 2025, SHA-256 dd0b4dc6983c07fafd89ba83b0c7f514aa16977654eaeb4c9fc8884ed359d98e | 354,011 | 4,008 | -0.387591 | -5.387591 | -10.387591 | -5.060975 |

All three source-wall series contained **one backward timestamp jump** and multiple other discontinuities, handled as segment breaks without sorting or silently repairing. Results are **not evidence of a profitable edge**. This fixed 15-minute confluence proxy is negative after a hypothetical 5 bps round-trip charge in each archive. The zero-cost positive NSXUSD gross average is small and cannot be interpreted as tradable without executable bid/ask, financing and broker-specific costs.

These are three selected annual archives, **not all suitable archived years**. The sample, horizon and later-period segment are exploratory and not independently preregistered. Market-data rights and source authenticity remain unverified. Floating-point calculations are descriptive and not cash-ledger grade.

## Reproduction and further gates

~~~bash
cd backend
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_cost_sensitivity.py
PYTHONPATH=. python - <<'PY'
import json
from app.offline_m1_cost_sensitivity import audit_histdata_ascii_zip
report = audit_histdata_ascii_zip('/private/path/to/HISTDATA_COM_ASCII_XAUUSD_M12025.zip', instrument='XAUUSD')
print(json.dumps(report, indent=2))
PY
~~~

Before interpreting historical performance, verify licensed provider provenance, timestamp convention and DST, original archive integrity, bid/ask side and executable costs, complete sessions, no lookahead in the full research pipeline, frozen hypotheses, genuinely untouched chronological holdouts, and stress scenarios including financing. Do not connect these outputs to automatic signals, risk gates or broker orders. No source data, secrets or credentials are included.
