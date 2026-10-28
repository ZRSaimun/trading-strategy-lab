# Original ASCII archive → SQLite row-parity preflight (offline)

This is an **opt-in, read-only staging census**, not a data repair, authenticated source clock, trading signal, backtest, license check, or execution permission.

Run from `backend/` against an owner-authorized local original ZIP and SQLite snapshot:

```bash
python -m app.offline_archive_sqlite_row_parity /private/original.zip /private/research.sqlite \
  --dataset-id <64-lowercase-hex> --expected-archive-sha256 <64-lowercase-hex>
```

The tool verifies the compressed ZIP SHA-256 before and after a pinned read-only SQLite transaction. It streams one HistData ASCII CSV (with optional small status TXT) in original row order, preserving backward and duplicate timestamps. It reconstructs the existing importer's **strictly increasing timestamp** admission rule under the **stored, unverified fixed UTC offset**. Each admitted row must match the SQLite timestamp, original source-member name, original CSV line number, and FLOAT-round-tripped OHLC values. It reconciles admitted and quarantined counts against the READY dataset metadata. Any disagreement raises an error and produces no successful report.

Only aggregate counters and identity hashes are printed, never original prices or licensed row contents. Parsing and ZIP reads are bounded; ZIP member CRC is consumed. The SQLite database is opened `mode=ro`, `query_only=ON` with an explicit read snapshot. No archive extraction, vendor calls, DB writes, live routes, orders, or charges.

**Decimal fidelity and precision counters:** `original_decimal_values_not_preserved_by_binary_float` compares the source text's exact `Decimal` with `Decimal.from_float(stored_float)` (the exact stored binary64 value); `exact_original_decimal_storage_verified` is true only if **all** accepted OHLC values match under this exact comparison. `original_decimal_values_not_preserved_on_shortest_roundtrip` instead compares with `Decimal(str(stored_float))`, the shortest decimal representation that round-trips to the same binary float. The legacy `original_decimal_values_not_preserved_by_float` key is retained as an alias for this **shortest-roundtrip** counter for existing report consumers, **not** a binary-storage fidelity measure. `shortest_decimal_roundtrip_verified` is separate from exact storage. For example, `100.1` passes the shortest-roundtrip check but fails exact binary storage. SQLite FLOAT values can be perfectly adequate for a declared importer parity check while not preserving exact original decimal representation. The importer itself uses FLOAT, and matching that conversion cannot prove original prices are authentic.

**Independent full-population evidence (Loop 1, 28 Oct 2026):** 11 original source ZIPs reconciled against the read-only owner research SQLite snapshot with 3,674,038 source rows, 3,673,378 admitted, 660 identical quarantined rows, zero conflicting repeats, and zero accepted-row FLOAT/lineage mismatches. Across 14,693,512 OHLC values, 14,520,002 differed under exact `Decimal.from_float` comparison, while zero differed under shortest `Decimal(str(float))` comparison. These figures were reported by the independent data-provenance workstream and are **not** a fresh archive replay by this Loop 2 change; they do not establish vendor rights, timezone authenticity, ASK-side execution, prospective holdout, or profitability. See [independent reconciliation](https://github.com/ZRSaimun/trading-strategy-lab/blob/loop1/collision-day-provenance-20261025/docs/independent-archive-sqlite-reproduction-20261028.md).

**Other limitations:** Invalid source CSV records fail closed instead of attempting to reproduce every legacy import error category. Only one source CSV member is supported; no timezone/DST inference, provider provenance, market calendar, spread, financing, or executable BID/ASK evidence is established. A changing file can evade a two-pass digest if replaced and restored between passes; use immutable, access-controlled inputs for independent assurance.

The independently reproduced 660 extra original rows and 44 raw-order M15 windows across 11 archives require a frozen quarantine policy and explicit cohort treatment before interpreting historical returns. A clean parity report supports a *declared-offset, accepted-row FLOAT reconciliation* only. It does not resolve raw-source-order versus quarantined-M1 M15 population differences or justify selecting an apparent profitable confluence subgroup.

Do not merge or deploy research code without full backend/frontend/PostgreSQL/Docker/cloud checks and independent production restore/rollback/health/hosting verification. No broker execution or order permission is provided.
