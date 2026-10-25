# EUR/USD paired M1 BID/ASK preflight (offline research only)

This additive Python module inspects **user-supplied** `Etc/UTC,Open,High,Low,Close,Volume` M1 CSV exports. It does not download, import, trade, contact brokers, change production data or commit owner-provided prices. It is separate from Gold CSV and HistData ZIP pipelines; never relabel instruments.

## Regression tests

From the repository root with backend development dependencies:

```sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_eurusd_bidask_preflight.py
```

For local private research, import `inspect_eurusd_pair` from `app.eurusd_bidask_preflight` and supply the original BID/ASK file **bytes**. The module has no HTTP upload route. Its synthetic regression fixtures are not historical price evidence.

## Fail-closed contract

- Require exact `Etc/UTC` header, finite positive internally consistent OHLC, finite nonnegative volume, strictly increasing minute-aligned UTC timestamps, bounded 25 MB and 300,000 rows per side.
- A timezone-naive timestamp is interpreted as UTC **only** because the exact export header declares `Etc/UTC`; any explicit non-UTC offset is rejected.
- Require identical BID/ASK timestamp sequences and non-crossed OHLC. Do not forward-fill, merge conflicting source streams, guess spreads or repair malformed data.
- Return raw-byte SHA-256 identities, observed UTC range, observed >1-minute gaps and observed open/close spread range (pips). These are **not** executable broker quotes, spread distributions or proof of provider authenticity.
- Always mark `approved_for_backtest=false`, `broker_executable_quotes=false`, `licensed_use_verified=false`, `profitable_pattern_proven=false`. Volume remains unverified. A separate rights, provenance, source/timebase and broker-cost review is mandatory.

## Owner upload result (2026-10-25)

Two EUR/USD CSVs named for **2021-01-01** (BID and ASK) were received. Each was **34 bytes, header only, zero candles**. Local preflight rejected them with `BID: zero candles; header-only exports cannot be backtested`. This documents only a quality failure; no real prices, signals, spreads or profit estimates exist in those uploads. No uploaded file was committed.

## Research plan once actual rights-cleared history exists

First validate a small completed trading-day sample from the same provider, then request multi-year BID/ASK observations and documented timebase/rights. Freeze the 1H trend + 15m pullback baseline alongside existing CRT/FVG definitions before testing; isolate sessions, spread and preannounced news windows using **first-available** timestamps. Use chronological development/validation/untouched holdout, robust friction scenarios, trade-level confidence intervals and multiple-testing corrections if enough trials exist. No pattern may be called profitable based on synthetic tests or this metadata-only preflight.
