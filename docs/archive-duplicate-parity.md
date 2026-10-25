# Duplicate-aware HistData ASCII / MetaTrader M1 parity (Loop 1)

`backend/app/archive_duplicate_parity.py` compares two distinct, immutable ZIP files **in original row order**, preserving adjacent repeated and backward wall-clock minutes rather than deduplicating, sorting, or repairing them. It is intended for quarantined source-format pairs that the strict monotonic `archive_format_parity.py` must reject. It does **not** replace the strict verifier or enable any dataset for research.

Run privately from `backend`:

```sh
PYTHONPATH=. python -m app.archive_duplicate_parity /private/gold_ascii.zip /private/gold_mt.zip --instrument XAUUSD --provider HistData
PYTHONPATH=. python -m unittest discover -s tests -p test_archive_duplicate_parity.py -v
```

Exactly one flat CSV ZIP member per file is required. The parser enforces row/uncompressed-byte/physical-line bounds, rejects invalid timestamps, OHLCV, nonfinite prices, encrypted or symlink members, and reads through ZIP CRC checks. It uses a bounded `readline(1025)` rather than allocating an arbitrary-length line before checking its size. HistData input is treated as **unquoted** CSV: quoted multiline fields are rejected, while ordinary LF/CRLF records remain supported. The byte budget uses ZIP-declared uncompressed size and is not a proof of source authenticity. It compares naive wall-clock minute stamps and **exact decimal OHLC** by row ordinal. Volume is counted when zero but is not compared as an independent market signal. If rows are misaligned, it reports ordinal mismatches rather than inferring a best-match repair. Mismatch examples contain only row ordinals and categories, never prices or secrets.

`EXACT_ROW_SEQUENCE_WITH_ANOMALIES` means two formats encode the same ordered observations **including repeated or backward minutes**. This is useful for diagnosing format conversion, but is *not* two independent confirmations of price accuracy. Adjacent repeated-minute counters do not claim to detect nonadjacent duplicates; they cannot validate DST conventions. `EXACT_ROW_SEQUENCE` likewise proves neither vendor authenticity nor correct timestamps.

All results explicitly mark source clock, authenticity, usage rights, market calendar, executable bid/ask, research import and trading as **unverified/disabled**. The actual original ZIPs, provider timebase, permissions, provenance and downstream staging remain separate gates. No source ZIPs, report hashes, credentials, OHLC values, or private paths are committed to this public repository. No provider requests, DB writes, subscriptions, deployment or orders occur.
