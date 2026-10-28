# Read-only SQLite M1 replay against the frozen Decimal sweep engine

**Scope:** Offline staging research, not a live trading feature. This adapter consumes
one explicit `historical_datasets` record and its `historical_candles` from a
locally held research SQLite database. It uses the existing frozen
`offline_sweep_probe.research` engine rather than creating a new strategy.

```bash
cd backend
python -m app.offline_sweep_sqlite_replay /private/path/research.sqlite \
  --dataset-id <64-character-dataset-id> \
  --expected-archive-sha256 <64-character-original-archive-sha256>
```

Both hashes are **caller-declared identity checks** against SQLite metadata.
They do not verify the original ZIP bytes or its license, source timestamp
convention, provider, venue, or broker quote side. Do not put private paths,
archive names, candle prices or source hashes in public PR comments.

The adapter uses a SQLite read-only connection with `query_only=ON`. An
explicit read transaction pins dataset metadata and candle rows to the same
SQLite snapshot, including when another process commits into a WAL database
between those two queries. This prevents mixed-revision research reports; it
does **not** authenticate either revision or guarantee a later replay sees the
same data. Preserve the database snapshot and original archive separately for
reproducible comparisons. It
requires `READY` HistData ASCII metadata, an explicit matching original
archive SHA-256 declaration, a bounded accepted row count, one strictly
increasing source-line lineage, minute-aligned UTC epochs, positive finite
OHLC with valid geometry, and nonnegative finite stored volume. It never
fills missing minutes. M15 bars require 15 consecutive M1 rows aligned to
UTC quarter hours. Gaps split continuity segments; partial buckets are
discarded and counted. Dataset accepted rows must match the actual census.
Any failed check aborts without a successful research report.

**Precision limitation:** This SQLite export stores OHLC as binary FLOAT.
Converting `str(float)` to `Decimal` before replay does **not** restore
the original HistData ASCII decimal strings. Therefore this replay is useful
for checking the committed Decimal engine on the existing imported dataset
and finding population differences, but it is **not** exact raw-archive
Decimal parity. The recorded `utc_offset_minutes` is a declared importer
interpretation, not authenticated source timezone evidence. Session/DST
validation, original ZIP SHA verification, provider entitlement, BID/ASK,
financing, spread and executable fills remain outstanding.

Output is bounded to dataset identity, population/quality counts, fixed
development/exploratory-later cohort censuses, and existing illustrative
0/5/10/20 extra-bps observed-only scenario means. It intentionally excludes
raw candles, source lines, private file paths, and any order interface.
Unknown exits are counted, never imputed; later-period results are already
inspected exploratory data, **not an untouched holdout**. Historical
execution, slippage, financing, fillability, and profitability are unverified.
The output always says `may_execute_order=false`.

The new synthetic tests cover source isolation, exact stored-row accounting,
gap-induced partial bars, corrupt geometry, explicit source identity,
read-only behavior and machine-readable output. A successful test does not
substitute for a replay on the owner's private dataset, independent original
archive verification, prospective protected holdout, or real executable costs.
No production database should be replaced with the research SQLite export.
