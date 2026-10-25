# Offline historical archive lineage observations (Loop 1)

Run from `backend` with an existing untrusted offline HistData audit report:

```sh
PYTHONPATH=. python -m app.archive_inventory_lineage /private/histdata-audit.json
PYTHONPATH=. python -m pytest -q tests/test_archive_inventory_lineage.py
```

The CLI first runs the existing strict `histdata_audit_triage` validator, then produces **only cross-archive metadata observations**. It never opens or repairs ZIPs, imports prices, accesses provider credentials, sends network requests or changes database rows. No executable price, license, source signature, order route, live status or profit claim is inferred.

A `canonical_digest_missing` value means the original scanner did not provide a canonical BID-OHLC digest for that archive; it does not mean the file is corrupt. A `claimed_same_digest_pairs` value counts pairs sharing the same **reported** canonical hash. It does not independently authenticate a provider, and ASCII/MetaTrader conversions of the same data are not two independent sources. A `claimed_digest_scope_conflicts` value means a shared digest is associated with different declared instruments or observed endpoint ranges; that requires independent investigation.

`same_instrument_endpoint_range_overlap_pairs` counts pairs whose **reported first/last UTC windows** intersect. It does **not** establish that even one observed candle timestamp overlaps: markets can close or have gaps. Neither overlap nor hash equality authorises deduplication or merging. The output omits source hashes and OHLC values and caps example pairs at 50. All outputs explicitly keep `research_ready`, `can_auto_import`, `live` and `may_execute_order` false.

For the 27-archive audit prepared 25 October 2026, 25 summaries have no canonical digest and the two October Gold ASCII/MetaTrader archives report the same canonical digest and overlapping endpoint ranges. These are scanner assertions only; the original ZIP bytes, source-clock convention, reuse rights and actual candle parity remain unverified. Coordinate independent ZIP checks with draft PR #43 and readiness gates with draft PR #41 before any disposable staging import. Do not merge or deploy without latest-head CI, branch reconciliation, verified backup restoration, rollback and health checks.
