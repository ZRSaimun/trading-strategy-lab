# Original ASCII archive → SQLite row-parity preflight (offline)

This is an **opt-in, read-only staging census**, not a data repair, authenticated source clock, trading signal, backtest, license check, or execution permission.

Run from `backend/` against an owner-authorized local original ZIP and SQLite snapshot:

```bash
python -m app.offline_archive_sqlite_row_parity /private/original.zip /private/research.sqlite \
  --dataset-id <64-lowercase-hex> --expected-archive-sha256 <64-lowercase-hex>
```

The tool verifies the compressed ZIP SHA-256 before and after a pinned read-only SQLite transaction. It streams one HistData ASCII CSV (with optional small status TXT) in original row order, preserving backward and duplicate timestamps. It reconstructs the existing importer's **strictly increasing timestamp** admission rule under the **stored, unverified fixed UTC offset**. Each admitted row must match the SQLite timestamp, original source-member name, original CSV line number, and FLOAT-round-tripped OHLC values. It reconciles admitted and quarantined counts against the READY dataset metadata. Any disagreement raises an error and produces no successful report.

Only aggregate counters and identity hashes are printed, never original prices or licensed row contents. Parsing and ZIP reads are bounded; ZIP member CRC is consumed. The SQLite database is opened `mode=ro`, `query_only=ON` with an explicit read snapshot. No archive extraction, vendor calls, DB writes, live routes, orders, or charges.

**Limitations:** FLOAT equality does not prove exact source Decimal preservation. The report counts values whose original Decimal differs from `Decimal(str(stored_float))`. The importer itself uses FLOAT, and matching that conversion cannot prove original prices are authentic. Invalid source CSV records fail closed instead of attempting to reproduce every legacy import error category. Only one source CSV member is supported; no timezone/DST inference, provider provenance, market calendar, spread, financing, or executable BID/ASK evidence is established. A changing file can evade a two-pass digest if replaced and restored between passes; use immutable, access-controlled inputs for independent assurance.

The earlier observed 660 extra original rows and 44 raw-order M15 windows across 11 archives must be rechecked with original files. A clean parity report supports a *declared-offset, accepted-row FLOAT reconciliation* only. It does not resolve raw-source-order versus quarantined-M1 M15 population differences or justify selecting an apparent profitable confluence subgroup.

Do not merge or deploy research code without full backend/frontend/PostgreSQL/Docker/cloud checks and independent production restore/rollback/health/hosting verification. No broker execution or order permission is provided.
