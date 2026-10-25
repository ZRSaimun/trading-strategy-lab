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
