# Read-only archive preflight

Run from backend:

```
python -m app.archive_validation /path/to/archive.zip --instrument NSXUSD-CFD --provider HistData --utc-offset-minutes=-300
```

The offset above is an example, not verified source metadata. Verify the archive's documented convention before choosing it. This version supports HistData ASCII M1 semicolon CSV and MetaTrader M1 comma CSV (`--format mt`). DST-local timestamps are not supported. It never extracts archive paths, changes prices, writes candles, or calls a vendor.

The JSON manifest includes a streaming SHA-256, member sizes/CRC, row counts, UTC range, bounded issue samples and quality counters. ZIP CRC is checked while consuming supported members; ZIP/decode failures abort rather than return a successful report. Unsupported members are reported. The file/member names do not establish source authenticity or licensing.

Duplicate adjacent timestamps and backward jumps relative to the last accepted timestamp are flagged and excluded from valid counts. Issue locations are quarantine candidates; original rows remain in the immutable input archive. Cross-member collisions still require provider-aware database ingestion. Gaps are observations, not proven missing trading minutes. Zero-volume rows remain counted and flagged; no volume inference is made. Negative prices are not automatically invalid (some instruments have traded negative).

Bounded archive member count, declared uncompressed bytes, row budget, CSV field limits and 100 issue samples limit resource consumption. This is an offline validation foundation, not the resumable ingestion pipeline. It does not repair the existing replacement importer, add job processing or change production schema.

Source verified 24 October 2026: https://www.histdata.com/f-a-q/data-files-detailed-specification/ specifies fixed EST without DST and bid OHLC for both formats. Use -300 minutes for unmodified files conforming to this convention; archive origin still requires verification. Bid-only bars cannot establish historical spreads.
