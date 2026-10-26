# EUR/USD paired M1/H1 BID/ASK preflight (offline research only)

This additive Python module inspects **user-supplied** `Etc/UTC,Open,High,Low,Close,Volume` M1 **or native H1** CSV exports. It does not download, import, trade, contact brokers, change production data or commit owner-provided prices. It is separate from Gold CSV and HistData ZIP pipelines; never relabel instruments.

## Regression tests

From the repository root with backend development dependencies:

```sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_eurusd_bidask_preflight.py
```

For local private research, import `inspect_eurusd_pair` from `app.eurusd_bidask_preflight` and supply the original BID/ASK file **bytes**, with a mandatory explicit `interval='M1'` or `interval='H1'`. Never call the M1 engine on an H1 export or upsample H1 candles into M1. The interval is caller-declared, not independently source-authenticated. The module has no HTTP upload route. Its synthetic regression fixtures are not historical price evidence.

## Fail-closed contract

- Require exact `Etc/UTC` header, finite positive internally consistent OHLC, finite nonnegative volume, strictly increasing UTC timestamps aligned to the **declared** 60-second M1 or 3,600-second H1 interval, bounded 25 MB and 300,000 rows per side. Numeric cells must use ASCII decimal notation (optional exponent); reject Python `float()`-accepted underscores and Unicode digits instead of silently interpreting malformed source values. `NaN` and infinity are rejected; whitespace surrounding otherwise valid numeric fields is tolerated.
- A timezone-naive timestamp is interpreted as UTC **only** because the exact export header declares `Etc/UTC`; any explicit non-UTC offset is rejected.
- Timestamps must explicitly contain `YYYY-MM-DD`, a `T` or space separator, and `HH:MM:SS`. Optional fractional seconds have 1–6 digits; optional offsets use `Z` or `±HH:MM` (only zero offset passes). Date-only, reduced-time, compact/week-date forms, arbitrary separators and excess fractional precision are rejected before datetime parsing. Python must not invent midnight or truncate a submicrosecond observation into a minute-aligned candle. Calendar validity and interval alignment remain independently required. This deliberately narrows accepted syntax; an unsupported export needs source/timebase review, not automatic repair.
- Reject the RFC 3339 `-00:00` *unknown local offset* marker even though Python parses it as UTC. Only a known `Z` or `+00:00` offset (or an explicitly header-declared naive UTC time) can satisfy the UTC preflight. This is a timestamp provenance guard, not broker or vendor authentication.
- Reject embedded CR or LF inside **quoted CSV cells** before trimming timestamp or numeric whitespace. Otherwise Python's CSV parser can accept a multi-physical-line timestamp/price/volume as one logical candle after `.strip()`, concealing malformed source row boundaries. Row diagnostics use the CSV reader's physical-line counter. Ordinary CRLF row separators remain supported.
- Require identical BID/ASK timestamp sequences and non-crossed OHLC. Do not forward-fill, merge conflicting source streams, guess spreads or repair malformed data.
- Reject nonzero source decimal OHLC or volume values that **underflow to floating-point zero** (for example, `1e-400`). Otherwise a positive price or volume could silently be reported as an observed zero. True source zero volume remains valid; this is a report-integrity guard, not a market-data authenticity check. Synthetic BID/ASK and M1/H1 regressions cover both fields.
- Compare source decimal OHLC and BID/ASK values **before binary-float rounding**. Two lexically distinct high-precision prices may collapse to the same Python float, concealing an actual crossed quote or an OHLC close above high. Regression tests cover both M1/H1 and BID/ASK violations as well as a valid tiny positive spread. Descriptive rounded spread statistics are not tick-level execution evidence, and input precision is not independently authenticated.
- Return raw-byte SHA-256 identities, observed UTC range, gap-event count (`observed_gaps_over_interval`), unrepresented M1/H1 slots between observed rows (`observed_unrepresented_interval_slots`), largest interbar gap in seconds (`largest_observed_gap_seconds`; zero when contiguous), and observed open/close spread range (pips), plus the **count**, nearest-rank **p50** and **p95** of matched candle-**close** spread observations. The percentile values select observed close samples (no interpolation or fabricated intrabar quote); they are not tick-level spread distributions or executable Fusion Zero quotes. With few candles, percentiles are descriptive only and do not establish stable tails or broker costs. The slot count is **not** a count of missing tradeable candles: weekends, holidays and other market closures may explain some or all slots, and the validator does not infer a session calendar. These are **not** executable broker quotes, spread distributions or proof of provider authenticity.
- Exact paired-close spread extrema are also exposed as decimal strings in `observed_close_spread_min_exact_pips` and `observed_close_spread_max_exact_pips`. This avoids float subtraction rounding a genuine sub-ULP positive source spread to zero. Existing rounded p50/p95 and open/close statistics may still show zero at their display precision. These are source-file OHLC observations, **not** independently verified synchronous tick spreads or executable broker costs; M1/H1 synthetic regressions cover this distinction.
- For diagnostics, `observed_gap_samples_first_10` records the two observed UTC boundary timestamps and unrepresented interval-slot count for at most the **first ten** gaps; `observed_gap_samples_truncated` identifies additional unsampled gaps. The complete gap and slot counters are unaffected by this sample cap. Neither a sampled gap nor its slot count proves missing tradable candles; a verified market calendar and source-level quote availability are still required. No timestamps are filled or inferred.
- Always mark `approved_for_backtest=false`, `broker_executable_quotes=false`, `licensed_use_verified=false`, `profitable_pattern_proven=false`. Volume remains unverified. A separate rights, provenance, source/timebase and broker-cost review is mandatory.

## Owner upload result (2026-10-25)

Two EUR/USD CSVs named for **2021-01-01** (BID and ASK) were received. Each was **34 bytes, header only, zero candles**. Local preflight rejected them with `BID: zero candles; header-only exports cannot be backtested`. This documents only a quality failure; no real prices, signals, spreads or profit estimates exist in those uploads. No uploaded file was committed.

## Native H1 upload assessment (2026-10-25)

A new pair of user-supplied EUR/USD hourly BID/ASK CSVs (1–25 October 2026 export window) contained **405 matching hourly timestamps** from 1 October 00:00 UTC to 23 October 20:00 UTC. Independent local structural inspection found no crossed BID/ASK OHLC and three 49-hour interbar gaps compatible with weekend closures. This is a **format/coverage assessment only**, not authentication of vendor, rights, execution prices, actual market sessions, or historical performance. The H1 files must be explicitly inspected with `interval='H1'`; they cannot support a causal 15-minute entry or intrahour fill test. No owner prices, raw files, private dataset hashes, or derived strategy results were committed.

## Bounded observed-gap boundary audit (25 October 2026)

The existing offline EUR/USD M1/H1 preflight now exposes at most ten explicit observed gap boundaries, alongside complete gap-event and unrepresented-slot totals. Synthetic tests cover a three-minute M1 gap, a 49-hour H1 interval, contiguous H1 observations, and twelve distinct M1 gaps (ten samples, twelve counted). This is bounded **data-quality evidence**, not a missing-market-candle census, a trading-session calendar, broker-executable quotes, or permission to backtest. This update also reconciles the draft PR branch with the latest inspected main; no deployment or merge into main was performed.

## Research plan once actual rights-cleared history exists

### Candle-close spread sampling regression (25 October 2026)

The offline preflight now reports observed paired-close spread p50/p95 with an explicit sample count. Synthetic tests verify a five-close ordered distribution, one-observation behavior, and continued fail-closed research/broker authorization flags. The quantiles do not include unpaired intrabar highs/lows, do not imply synchronized tick spreads, and must not be inserted as observed Fusion Zero transaction costs. No strategy logic, broker connection, or executable orders are added.

### Timestamp integrity regression (25 October 2026)

Synthetic regressions reproduce date-only/reduced-time BID or ASK rows being silently matched to midnight, and submicrosecond fractions being truncated to an aligned time. Additional M1/H1 synthetic cases verify contiguous windows, multiple intraday gaps and a 49-hour closure-sized interval, without converting unrepresented time slots into missing-market claims. Strict parsing rejects these cases while preserving full UTC timestamps and header-declared naive UTC forms for M1/H1. Historical upload assessments above are prior-session records, **not revalidated in this session**: the owner CSV bytes were not available. No actual market data or profitable strategy is established by these tests.

No environment variables, migrations, HTTP routes or frontend contracts change. The offline function now rejects previously accepted ambiguous timestamp syntax. PR #61 merged while this follow-up was being verified; keep the timestamp-fix follow-up draft pending exact-head CI and explicit release approval; rollback is a revert of the timestamp-validation commit, without data migration. Main pushes can trigger Pages and Render deployments.

First validate a small completed trading-day sample from the same provider, then request multi-year BID/ASK observations and documented timebase/rights. Freeze the 1H trend + 15m pullback baseline alongside existing CRT/FVG definitions before testing; isolate sessions, spread and preannounced news windows using **first-available** timestamps. Use chronological development/validation/untouched holdout, robust friction scenarios, trade-level confidence intervals and multiple-testing corrections if enough trials exist. No pattern may be called profitable based on synthetic tests or this metadata-only preflight.
