# Read-only historical snapshot drift report

Before replacing a previously imported historical XAU/USD window, compare two **independently reconciled** Twelve Data staging imports. The report shows the number of shared UTC minutes with changed normalized OHLC, newly observed minutes and minutes no longer present, with bounded timestamp-only samples. It never prints prices, alters a dataset, contacts a provider, or approves replacement.

Prepare `manifest.json`, exact immutable `snapshot.json`, and `candles.json` for **each** staging import as described in [offline staging reconciliation](provider-staging-reconciliation.md). Keep both sets in a private, disposable directory; do not copy secrets or production data. Only use datasets for which storage and comparison are contractually permitted.

From `backend`:

```sh
PYTHONPATH=. python -m app.provider_snapshot_drift \
  --previous-manifest /private/old/manifest.json \
  --previous-archive /private/old/snapshot.json \
  --previous-candles /private/old/candles.json \
  --current-manifest /private/new/manifest.json \
  --current-archive /private/new/snapshot.json \
  --current-candles /private/new/candles.json
PYTHONPATH=. pytest -q tests/test_provider_snapshot_drift.py
```

The input reader rejects final-path symlinks, nonregular and oversized files, duplicate JSON keys and nonstandard numeric constants. Each triplet must pass the existing manifest/archive/row/hash/quality provenance reconciler before comparison. Current server receipt must not precede the previous receipt; this is **not** authenticated provider chronology. Samples are limited to 0–20 timestamps per change category; all counts cover the bounded imported windows (up to 5,000 candles per version).

`NO_SHARED_OBSERVED_MINUTES` means the windows cannot be compared for revisions. `OBSERVED_VALUE_OR_COVERAGE_DRIFT` is a review flag, not proof of provider error: request-window differences, genuine revisions, closures or omissions can produce it. `SAME_OBSERVED_VALUES_AND_COVERAGE` only establishes equality of the compared normalized values. Both snapshots may still be unlicensed, unauthenticated or unrepresentative. No market calendar, executable bid/ask, live-feed latency, actual spread, backup recovery or provider entitlement is verified. All outputs explicitly set `live=false`, `may_replace_dataset=false` and `may_execute_order=false`. No production integration or live-order route is enabled.
