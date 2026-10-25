# Read-only HistData ASCII / MetaTrader M1 format parity

Run from `backend` after independently obtaining two licensed archives representing the **same instrument, provider and wall-clock coverage**:

```bash
python -m app.archive_format_parity /private/ASCII.zip /private/MT.zip --instrument XAUUSD-CFD --provider HistData
pytest -q tests/test_archive_format_parity.py
```

The tool never extracts files, edits prices, imports candles, accesses a vendor, or touches broker APIs. It streams one CSV member per ZIP, enforces size/row budgets and monotonic minute-aligned naive timestamps, validates OHLCV using exact decimal arithmetic, and consumes each member so ZIP CRC is checked. It compares OHLC at identical **wall-clock** timestamps and reports aggregate equal/conflicting/unmatched minute counts with bounded timestamp-only samples. Volume is *not* compared as price evidence. Negative oil prices are not automatically discarded.

`EXACT_WALL_CLOCK_PRICE_PARITY` is **not** permission to ingest or backtest. It does not authenticate the vendor, usage rights, UTC offset, DST convention, completeness, executable bid/ask, or historical provenance. `PARTIAL_WALL_CLOCK_PARITY` means the windows differ but share some minutes; `NO_SHARED_WALL_CLOCK_MINUTES` means no overlap; `PRICE_CONFLICT` means prices differ at at least one shared wall minute. Corrupt archives, invalid rows, duplicate/backward stamps, or ambiguous ZIP membership abort the entire comparison. Do not sort, silently repair, or infer time offsets to force a match. Different archive months, distinct providers, or different CFD/spot/futures identities must not be compared as if they were interchangeable.

This is an isolated diagnostic feeding the source-identity review process in draft PR #41 and independent chronological planning in PR #29. Private archive bytes, prices, hashes and individual comparison results must not be committed. All outputs have `research_ready: false` until independent source/timebase/rights verification is completed elsewhere. No return backtest or strategy edge is claimed.
