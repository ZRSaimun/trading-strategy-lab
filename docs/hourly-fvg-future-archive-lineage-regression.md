# Future timestamp must not rewrite completed FVG archive lineage

The synthetic regression `frontend/tests/hourly-fvg-future-archive-lineage-mutation.test.ts` independently changes the `datasetId` and `archiveSha256` of a completed hourly BID source declaration while reading only the timestamp of an unrevealed future bar. The causal as-of scanner must reject each retroactive source-declaration mutation with its specific snapshot-integrity error, read the future timestamp exactly once, and never access future OHLC, volume, or minute coverage.

The identifiers are source-declared labels, not independently verified authenticity receipts. This test proves a narrow in-memory snapshot boundary, not licensed history, authenticated broker quotes, volume provenance, trading performance, or profitability. Keep the PR draft, paper-only, unmerged and undeployed until independent review and real evidence are available.
