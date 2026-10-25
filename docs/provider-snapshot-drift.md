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

## Distinguishing shifted windows from coverage differences

The report separates added/removed observed minutes **within the intersection of the two observed endpoint ranges** from those **outside** it. The `observed_range_overlap` flag and nullable UTC bounds describe that endpoint intersection; `added_within_observed_overlap` and `removed_within_observed_overlap` are the more useful counts when checking whether the same historical interval contains different observed minutes. `added_outside_observed_overlap` and `removed_outside_observed_overlap` may arise simply because the importer requested a different window. `overlap_coverage_differs` reflects only the within-intersection additions/removals, not OHLC revisions; use `revised_shared_minutes` separately. Existing `outcome` and total count fields remain unchanged for compatibility.

**Important:** These ranges use the earliest and latest *observed* candle timestamps, not provider-declared request boundaries, trading sessions or a verified market calendar. An overlap does not prove that missing minutes were tradable; a non-overlap does not prove that either import was incomplete. No missing prices are invented and the report remains non-executing.
