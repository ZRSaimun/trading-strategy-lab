# Paginated historical archive discovery in the private terminal

The authenticated **Historical Archives** screen now requests the private `GET /api/history/datasets?offset=0&limit=200` endpoint and displays a **Load more archive datasets** control when the server returns `X-History-Has-More: true` and a valid `X-History-Next-Offset` header. This is compatible with the additive backend pagination in PR #19; that backend change must be merged before browsing beyond the first 200 archives works. The client now retains the first page's `X-History-Snapshot` SHA-256 inventory fingerprint and sends it on every later page as the `snapshot` query parameter. The backend rejects changes to the READY inventory with HTTP 409.

## Integrity and compatibility

- Archive IDs are 64-character lowercase hashes. Each listing must identify a READY dataset, a nonempty provider/instrument/format, and nonnegative import counts. Declared fixed UTC offsets and SHA-256 values are checked when supplied. A source hash identifies archive bytes; it is **not** a proof of licensing, authenticity, executable quotes, or market coverage.
- The client rejects repeated IDs within a page, overlapping IDs across pages, malformed response headers, non-monotonic pagination cursors, changed or missing inventory snapshots, and unexpectedly large responses. A 409 inventory conflict invalidates previously fetched listing pages and disables further paging until the user clicks **Refresh archive inventory**. This closes an offset-pagination race in which a concurrent new READY archive could otherwise shift page boundaries without an obvious duplicate or sort violation. The SHA-256 token is a listing-consistency fingerprint, **not** evidence of vendor authenticity or licensing. It never silently concatenates market candles from different ZIP archives.
- If the server has the old first-200-only API and omits pagination headers, the first response remains usable. If a server supports offset pagination but does not supply the inventory snapshot, the first page remains visible but further paging is disabled. In either case, the UI warns that additional archives **may be hidden**, rather than pretending the listing is exhaustive or requesting unsafe offset pages.
- **Fail-closed follow-up requests:** any error while loading an additional page (HTTP 409, changed snapshot, malformed source provenance, out-of-order/overlapping records, authentication failure, or transient network failure) now clears the previously loaded inventory and selected archive. The user must explicitly refresh from offset 0; stale partial lists are never retained as if complete. A network failure may require retrying, but no price records are changed.
- Pagination is owner-authenticated and same-origin. Requests are aborted on unmount. Each click loads at most 200 metadata rows, not historical candle contents.
- The selected dataset shows its full dataset ID, declared fixed UTC offset and source SHA-256 when available. The actual historical candle chart remains read-only and isolated by dataset ID.

## Limitations

- The backend currently caps `offset` at 1,000,000. This UI refuses cursors beyond that limit.
- The Backtesting archive selector is **not** changed by this PR. It still needs a separate paginated discovery implementation before it can select archives beyond the first 200.
- The UI does not import ZIP files, verify exchange trading sessions, activate data providers, download live quotes or place orders.
- No production database, Render settings, historical prices or broker accounts are changed.

## Verification

Run `cd frontend && npm ci && npm test && npm run build` and the repository's backend, Docker and free-cloud smoke CI. The deterministic `frontend/tests/archive-discovery.test.ts` suite covers legacy responses, 201+ archives, cursor validation, duplicate identity rejection, malformed provenance, same-origin credentials, exact snapshot forwarding, 409 inventory changes, mismatched/missing tokens, and HTTP failures. On the actual private server, verify the backend pagination headers are present and that a real READY archive selection still renders its own candles.
