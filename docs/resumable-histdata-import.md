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
- `GET /api/history/{dataset_id}/candles?timeframe=5m&limit=2000`: paged observed OHLCV aggregations; `before` must be aligned to timeframe bucket start.
- Response includes `has_more` and `next_before`, which can be used for an older page.
- API never returns an unfinished dataset. All endpoints use the existing owner-session authentication.
- Bid-only historical OHLCV is explicitly labelled **HISTORICAL ONLY**, not live or executable.

## Testing and limitations

Local isolated tests cover fixed-offset parsing, malformed rows, quarantine, source isolation, no overwrite, paused/resumed imports, ASCII/MT parsing and paginated authenticated historical responses. Before production activation, perform PostgreSQL migration/recovery and authenticated browser acceptance tests against a **staging** database.

This is not a live data source, a strategy profitability claim, or a completed historical backtesting engine.
