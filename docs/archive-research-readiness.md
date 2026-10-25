# Offline archive research readiness gate (Loop 2)

`frontend/lib/archive-research-readiness.ts` is a pure metadata-only gate that prevents an analyst from silently pooling duplicate, time-ambiguous or source-conflicted historical ZIPs before CRT/ICT confluence studies. It neither opens ZIPs nor changes market data, databases, orders, API credentials or deployments. The input is a separate **owner-prepared preflight inventory**; this is not a parser, provenance authenticator or source license checker.

## Frozen behavior

- Require a unique archive ID, 64-character SHA-256 metadata, supported HistData ASCII/MetaTrader M1 format, positive row count, consistent nonnegative quality counters, bounded owner evidence references, and a declared **fixed** UTC offset and UTC range. DST-local timestamp streams are unsupported. Filename and checksum alone are **not** proof of source, timezone or rights.
- Quarantine any malformed/invalid OHLC row or nonmonotonic/duplicate timestamp observation. No silent deletion or conversion of these observations into winning/losing trades.
- Quarantine missing source, usage-rights or timebase references; missing UTC ranges remain unverified even if price rows parse.
- For frozen `VOLUME_CONFIRMED` research, any zero-volume rows quarantine that archive. For `PRICE_ONLY`, zero volume is not interpreted as observed tick volume.
- Keep the lexicographically first archive ID for a byte-identical, same-identity ZIP group as a **metadata review candidate**; quarantine other copies. Identical bytes with conflicting instrument/provider/format labels quarantine the entire group.
- Quarantine both archives when different ZIP bytes from the **same provider and instrument** have overlapping inclusive UTC ranges. Alternate ASCII/MT formats are not assumed independent observations. Different providers remain separate source identities and are **not** automatically pooled.
- Record observed >1-minute gaps without labeling them missing trading minutes. Session calendar and daylight saving must be independently verified.
- The returned `metadataCandidateForIndependentReview` is **not permission to backtest**: `approvedForBacktest`, `independentlyVerified` and all live-trading flags are always false. References are declarations only. A separate trusted provenance, licensed-use, UTC convention and non-overlapping lineage approval is necessary.

## Evidence and limitations

The private 25 October 2026 read-only preflight reported 29 ZIP files, 3,813,712 M1 rows including duplicated/alternate formats, 430 duplicate/backward observations, 21,526 >1-minute gaps, zero reported volume throughout and two byte-identical duplicate pairs. These aggregate counts are **not** proof that every archive is unfit, that gaps are missing market sessions, or that there are 3.8m independent observations. Vendor timebase and licensing remain unverified. **No raw archive hashes, names, prices or private data are committed in this feature.**

Run synthetic tests: `cd frontend && node --experimental-strip-types --test tests/archive-research-readiness.test.ts`. Also run full `npm test`, `npm run typecheck`, production build, backend tests, Docker and cloud smoke before any merge. Coordinate with PR #28 (archive inventory) and PR #29 (independent holdout/lineage). No strategy parameter selection, P&L, untouched holdout, executable bid/ask or profitable trading edge is established.
