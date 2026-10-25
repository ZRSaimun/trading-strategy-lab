# Offline staging reconciliation — Twelve Data historical XAU/USD

This **read-only** command checks three copies of evidence from the **same disposable staging import**. It does not connect to a database, market-data provider, broker or production service; it never changes candles or sends an order. It is an internal consistency gate, **not** a backup/restore certification, proof of licensed rights, authenticated vendor source, market-session completeness, feed freshness, CFD spread or trade eligibility.

## Inputs from isolated staging

Prepare these files in a disposable private directory (not a web-served folder):

1. `manifest.json`: the JSON object stored as `records.value` for `dataset:XAUUSD-TD` after a staged manual import.
2. `snapshot.json`: the **exact bytes** of the immutable `<manifest.sha256>.json` source-field snapshot. Do not reformat or reconstruct this file.
3. `candles.json`: a JSON array of persisted `candles` rows for `XAUUSD-TD`, sorted by UTC `time`, including `instrument,time,open,high,low,close,volume,source,retrieved_at`. Export from the **same** isolated staging database. Never substitute a raw vendor payload for the vetted source-field snapshot.

Do not copy secrets, API credentials, production datasets, or real broker quotes into the test directory. Verify retention/display rights before using actual licensed provider data. If no authorised dataset is available, use only synthetic fixtures and leave the real-data gate blocked.

From the repository's `backend` directory:

```sh
PYTHONPATH=. python -m app.provider_staging_reconciliation \
  --manifest /private/staging/manifest.json \
  --archive /private/staging/snapshot.json \
  --candles /private/staging/candles.json
PYTHONPATH=. python -m pytest -q tests/test_provider_staging_reconciliation.py
```

The verifier accepts only bounded regular files, rejects final-path symlinks, ambiguous duplicate JSON keys, malformed numbers, altered snapshot SHA-256, inconsistent normalized candle prices/timestamps, missing or conflicting per-row provenance, manifest ranges, observed gaps and the complete saved quality report. It also checks the importer's exact historical source/volume labels, owner-only rights assertion, server-wall receipt and monotonic-elapsed clock labels, nonnegative request duration, original request timestamp, requested row limit and completed historical end boundary. These are **self-consistency checks only**; they do not authenticate the server clock, prove the rights assertion or establish the vendor's identity. Wall-clock timestamps are deliberately not compared with monotonic duration because wall clocks can be adjusted during a request. It returns a **metadata-only** `INTERNAL_STAGING_CONSISTENCY_ONLY` result or a generic `REJECTED` (exit code 2), without printing dataset prices, credentials or file contents. It does not infer missing market minutes from weekend gaps.

**A successful result is not a live feed or a deployment approval.** No market calendar, exchange or broker timestamp attestation, XAU/USD subscription entitlement, storage/display/non-display permission, bid/ask, executable spread, production backup restoration, rollback path or post-deployment health check is established by this tool. All execution and live flags remain false.

Before merge/deployment: complete full latest-head CI, independently review the changes against other workers, run this check against an owner-authorised disposable staging import, and separately verify production workspace identity, a tested restore/rollback and health checks. No real-money orders, paid calls, broker connection or automatic feed activation are part of this PR.
