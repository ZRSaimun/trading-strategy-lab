# Read-only HistData minute-collision quarantine manifest

The source-order parity comparator counts **adjacent** repeats and backward jumps, but a repeated minute can reappear later in a ZIP. `backend/app/archive_collision_quarantine.py` explicitly detects these **nonadjacent** repeated wall minutes and distinguishes identical OHLC repeats from conflicts with the first observed OHLC. No candle is dropped, sorted, repaired, imported or designated canonical.

Run offline from `backend`:

```sh
PYTHONPATH=. python -m app.archive_collision_quarantine /private/gold_ascii.zip --format ascii --instrument XAUUSD --provider HistData
PYTHONPATH=. python -m app.archive_collision_quarantine /private/gold_mt.zip --format mt --instrument XAUUSD --provider HistData
PYTHONPATH=. python -m unittest discover -s tests -p test_archive_collision_quarantine.py -v
```

It reuses the bounded ZIP parser in `archive_duplicate_parity`, including one flat CSV, an optional CRC-checked untrusted TXT status report, strict unquoted CSV, exact decimal BID OHLC and preserved source row order. It maintains an **exact** in-memory index of first observations (default maximum 500,000 distinct wall minutes); it **rejects without a partial success report** if that budget is exceeded. This is a deliberately conservative forensic workflow, not a large-archive ingestion pipeline. Increase the limit only when adequate memory is available. The report includes aggregate collision counts and up to 30 sample row ordinals and unverified wall-minute labels, but **never price values**. A minute's conflicting-repeat count compares each later occurrence against its first OHLC, without assuming the first is correct.

`QUARANTINE_REQUIRED` means observed duplicate wall minutes or backward jumps. `FORMAT_CHECK_ONLY_UNVERIFIED` is not a research approval: provider authenticity, source timebase, market closures, licensing and executable quotes remain unverified. All outputs keep research import, live data and order execution disabled. For the original October 2026 Gold files, use this against the immutable ZIP bytes in a private workspace; an independent offline scan of the original ZIP bytes observed 108 conflicting repeated rows across 105 distinct wall minutes per format, plus 54 backward jumps; those findings are not represented as a run of this repository CLI. The source ZIPs remain quarantined. Do not commit vendor archives, prices, personal paths or credentials.

## Wall-day collision evidence (unverified source clock)

The manifest also reports `first_collision_row_ordinal`, `last_collision_row_ordinal`, and sorted `collision_counts_by_unverified_wall_day` buckets. Each bucket separately counts repeated rows, conflicting repeats, distinct collided wall minutes and distinct conflicting minutes. Totals reconcile to the existing full-file counters. Dates are **naive source wall dates**, not verified UTC or exchange sessions; the report never chooses a canonical candle or releases any quarantine. A 3,660 collision-day output budget fails closed rather than emitting an unbounded manifest. A clean archive returns an empty bucket list and null first/last ordinals.

For the original October 2026 XAUUSD ASCII and MT ZIPs, an offline run against private, unchanged archive copies found 16,308 rows per format, 108 conflicting repeated rows spanning 105 distinct wall minutes, and 54 backward jumps per format. The first repeated row is ordinal 246 (source wall day 2026-10-01), and the last is ordinal 16,139 (2026-10-16); collisions span ten unverified wall days. This is **not** an independently authenticated price source or a license grant. Keep the original ZIPs out of Git and do not import the quarantined candles.

## Bind a scan to the exact ZIP bytes (read-only)

The CLI now streams a SHA-256 over the **compressed original ZIP bytes** before and after parsing. It refuses a successful manifest if the compressed archive changes between passes, exceeds the configurable compressed-byte budget (default 2,000,000,000 bytes), or differs from an optional known SHA-256. This guards against accidental file replacement between the earlier audit and this scan; it is **not** a vendor signature, entitlement, proof of provenance, or a guarantee against malicious concurrent modification. The report contains `archive_sha256`, `archive_size_bytes`, and `archive_integrity=MATCHED_BEFORE_AND_AFTER_SCAN` without exposing prices or private paths.

For example, when the owner has already independently recorded a ZIP SHA-256:

```sh
PYTHONPATH=. python -m app.archive_collision_quarantine /private/source.zip \
  --format ascii --instrument XAUUSD --provider HistData \
  --expected-sha256 <64-lowercase-hex-sha256> --max-archive-bytes 2000000000
```

A mismatch, malformed expected hash, exceeded byte budget, invalid ZIP, or detected in-scan change returns sanitized `REJECTED` and exits nonzero; there is no partial approval. The compressed ZIP is read twice, so plan I/O accordingly for large archives.

**Original-file verification (25 October 2026):** The repository's byte-identical Python modules were reconstructed and checked against their Git blob hashes, then the **actual CLI** was executed offline against the owner's original private October 2026 Gold ASCII and MT ZIPs. Each produced `QUARANTINE_REQUIRED`, 16,308 source-order rows, 108 repeated rows, 105 distinct collided minutes, 54 backward jumps, and 10 affected source-wall days. ZIP SHA-256 identities were `59d0ba305f161bf8d26985bece111c7701a7bbc8101d058a550fbaedad6fb31d` (ASCII) and `5fc9492e0e28b0936ca2d77e60e3a3a49b676d647f570b65056490f5e039209d` (MT). This establishes internal evidence consistency only. No vendor-origin signature, rights, source clock, market calendar, bid/ask spread, or price authenticity was verified. The archives remain quarantined and must not be auto-imported or treated as a live feed.
