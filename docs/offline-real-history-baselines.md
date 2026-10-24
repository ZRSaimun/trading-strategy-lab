# Offline real-history strategy baselines (research only)

This is a **reproducible, read-only evaluation tool** for private `historical_*` SQLite archive tables produced by `app.bulk_import`. Source archives remain private. Nothing in this module accesses a vendor, places an order, contacts Supabase or changes production data.

## How to run

```bash
cd backend
python -m app.research_baselines /path/to/research_real.sqlite --output /private/results.json
PYTHONPATH=. pytest -q tests/test_research_baselines.py
```

The tool reads **only** completed HistData ASCII dataset identities, and aggregates consecutive, timestamp-ordered one-minute candles into 1H OHLC; exact duplicates across archive boundaries are ignored but conflicts cause a hard failure. It does not combine different providers, incompatible instruments or Gold ASCII and MetaTrader representations.

## Pre-registered elementary research rules

- **Four-hour momentum**: Compare close prices of the previous four completed 1H bars. If rising, hypothesise long at the **next hour opening price** and exit at that hour's close. Otherwise hypothesise short.
- **Four-hour reversal**: Invert that hypothesis.
- Require at least 30 observed minute bars in every relevant hour and five consecutive clock hours (the preceding four plus the evaluated hour); ignore market closures and missing periods.
- Repeat with hypothetical round-trip cost scenarios **0, 5 and 20 basis points**.
- Show results overall, per calendar year, and split into 2016–2023 / 2024–2026 periods.

No fitting, optimisation, realistic broker execution, actual spread/financing, dynamic stops or portfolio capital sizing are implemented. The later split is **not a genuinely untouched holdout** because research results have already been viewed. The simple rules are negative controls; they do not demonstrate positive trading edge or actual broker P&L.

**Critical source limitation:** HistData's bid-only OHLC and often zero-volume placeholders do not support inference of executable historical bid/ask spreads or liquidity.

## Keep private artifacts private

Do not commit `.sqlite`, source ZIPs or full result JSON files into this public repository. Preserve their hashes, research metadata and licence terms in authorised private storage instead.

Before promoting any strategy into a trading workflow, require independent review, genuinely untouched out-of-sample periods, defensible cost assumptions and forward paper trading. The system is still research-only, without live execution.
