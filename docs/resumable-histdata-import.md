# Source-isolated HistData archive import (experimental)

This is a **review-stage local/private-server importer**. It does not replace the legacy small-CSV import endpoint or automatically deploy, backfill, merge datasets, or activate real-time feeds.

## Security and prerequisites

Use only archives that you have rights to use. Do not commit archives, local SQLite databases, or API credentials. The GitHub repository may be public. The data is bid OHLC and generally has zero volume; **do not treat it as bid/ask quotes or infer historic spreads**.

The import command uses the same `DATABASE_URL` and optional `DATABASE_SCHEMA=tsl_private` environment configuration as the FastAPI application, rather than placing credentials on the command line. Use a private, backed-up database; make schema changes only after review. Only PostgreSQL and SQLite are supported.

```bash
cd backend
# First run only: explicitly initialise isolated historical_* tables.
python -m app.bulk_import "/private/path/HISTDATA_COM_ASCII_NSXUSD_M12016.zip" \
  --instrument NSXUSD-CFD --provider HistData --format ascii \
  --utc-offset-minutes=-300 --rights-confirmed --init-schema

# Subsequent archives: omit --init-schema.
python -m app.bulk_import "/private/path/HISTDATA_COM_ASCII_NSXUSD_M12017.zip" \
  --instrument NSXUSD-CFD --provider HistData --format ascii \
  --utc-offset-minutes=-300 --rights-confirmed
```

Use `--format mt` for MetaTrader M1 archives. The `-300` minute offset represents **fixed UTC-05:00 (EST with no DST)** and is suitable only when archive provenance/conventions are confirmed. HistData's official specification: https://www.histdata.com/f-a-q/data-files-detailed-specification/

## Data storage and recovery

- Imports stream ZIP members without path extraction. Supported CSV members are checked on read for ZIP CRC errors.
- Archive SHA-256, provider, instrument, format, and timestamp offset form an immutable dataset identity.
- New tables: `historical_datasets`, `historical_candles` and `historical_quarantine`. Original `candles` and `records` tables remain unchanged.
- Atomic chunks commit rows and their restart checkpoints together; rerunning an identical completed archive does not duplicate it.
- Timestamp disorder, duplicates and malformed OHLCV are excluded and recorded as bounded quarantine samples; the original ZIP is never modified.
- An interrupted import can be resumed using the same unchanged archive; a dataset is exposed through the API only in the `READY` state.
- Each ZIP archive is a separate dataset. Do **not** treat results from separate providers or overlapping contracts as a continuous validated series.
- There is currently no distributed job queue, concurrency lease/lock, cloud upload UI, automated archive cleanup, cross-archive consolidation, or production migration benchmark. Run only one process per dataset and retain backups.

## Authenticated historical chart API

- `GET /api/history/datasets`: list READY imports as a JSON array (up to 200 by default). Use `?limit=100&offset=0` to paginate; `X-History-Has-More: true` and `X-History-Next-Offset` indicate another page. The legacy JSON array response and offset pagination remain compatible.
- **Consistent inventory paging (opt-in):** Save the `X-History-Snapshot` SHA-256 header from the first page, then send `?limit=100&offset=100&snapshot=<that-64-character-hash>` on every subsequent page. A change to any READY dataset's identity or listed provenance metadata returns HTTP **409** with no partial page; restart enumeration at offset 0. The hash is a consistency token for the READY listing, **not** a vendor signature, an immutable database snapshot, or proof of correct source licensing. Without passing `snapshot`, offset pages retain the legacy race risk. Each page computes the hash from one ordered, consistent SQL statement and streams only metadata (not candle prices); work scales with the number of READY datasets per page request, so benchmark before very large inventories. A new import that has not yet reached READY is not included.
- Dataset listings and candle pages include exact provider, instrument, archive SHA-256, declared fixed UTC offset and source file format; the candle page also includes accepted/rejected and zero-volume counters. These fields are provenance claims from the importer, **not** proof of timestamp convention or vendor authenticity. Do not combine different offsets, providers, contracts or archive hashes without explicit reconciliation.
- `GET /api/history/{dataset_id}/candles?timeframe=5m&limit=2000`: paged observed OHLCV aggregations; `before` must be aligned to timeframe bucket start and be a nonnegative, UTC-representable epoch-second cursor (at most `253402300740`, 9999-12-31 23:59 UTC). Invalid, negative or excessively large cursors return HTTP **422** rather than an internal datetime/SQL error.
- Response includes `has_more` and `next_before`, which can be used for an older page.
- API never returns an unfinished dataset. All endpoints use the existing owner-session authentication.
- Bid-only historical OHLCV is explicitly labelled **HISTORICAL ONLY**, not live or executable.

## Offline READY archive row reconciliation

For an existing **SQLite** research database, run the read-only integrity report
before interpreting imported archives as backtest-ready:

```bash
cd backend
python -m app.data_quality_research /private/path/research.sqlite --output /private/path/quality-report.json
```

The JSON `dataset_manifest` reports `observed_ready_rows` and
`accepted_count_matches` for **each READY dataset**, and the summary reports
`ready_dataset_count_mismatch`. This catches cases where one archive has
missing rows and another has extra rows, even when their provider/instrument/
format/UTC-offset group's combined count still equals its accepted total.
The existing `accepted_count_mismatch` is the **group-level** counter and is
retained for compatibility. Non-READY imports have null reconciliation fields;
their checkpoint counts are not treated as completed candles.

Counts include all stored rows for each dataset, not only distinct timestamps.
A matching count alone does **not** prove that prices, timestamps, provider
identity, licensing or archive completeness are correct. Investigate any
mismatch against the immutable ZIP/checkpoints before using that dataset;
this report never repairs or deletes data. It reads SQLite only and does not
automatically audit production PostgreSQL or load data into the live site.
Store JSON reports privately because they include source filenames.

## Testing and limitations

Local isolated tests cover fixed-offset parsing, malformed rows, quarantine, source isolation, no overwrite, paused/resumed imports, ASCII/MT parsing and paginated authenticated historical responses. Before production activation, perform PostgreSQL migration/recovery and authenticated browser acceptance tests against a **staging** database.

This is not a live data source, a strategy profitability claim, or a completed historical backtesting engine.
 

## Fail-closed research visibility for excluded rows

An archive with **any rejected row**, or with zero accepted rows, is now marked
`QUARANTINED` rather than `READY` when its resumable import finishes. The
accepted candles and bounded rejection evidence remain in the isolated historical
tables for manual inspection; nothing is deleted or repaired. Re-importing an
identical quarantined archive reports its existing state without promoting it.
A different corrected ZIP gets a new content-addressed dataset identity.

The authenticated history listing and candle endpoints also hide **legacy**
`READY` datasets whose metadata records rejected rows, zero accepted rows, or
an inconsistent seen/accepted count. This is a protective read-time gate for
existing databases; it does not rewrite old rows or claim that the remaining
`READY` archives are licensed, authentic, session-complete or backtest-ready.
The frontend may show fewer archives after this code is deployed. Independently
audit previously imported data and retain backups before considering any merge.

This does not implement source signatures, entitlement verification, session-aware
gap classification, or production restore/rollback certification. Source archives
with ambiguous repeated timestamps remain quarantined.
