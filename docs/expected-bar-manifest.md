# Explicit UTC expected-bar manifest (offline; not an exchange calendar)

`app.expected_bar_manifest.compile_expected_m1_manifest` compiles a bounded,
versioned **operator-declared** UTC minute population for the existing
`audit_declared_m1_receipts` census. This addresses a specific gap: a generic
24/7 minute range incorrectly treats documented market closures as missing
bars, while an arbitrary empty expected-minute list can hide missing bars.

**This does not verify the operator's calendar, source authenticity, feed
entitlement, provider identity, or clock.** The source string and SHA-256
fingerprint provide reproducibility, not independent attestation. No network,
broker, database, order execution, or paid call is made.

## Contract

- Supply the exact provider, symbol, venue, price side, calendar ID, calendar
  revision, and calendar source; no silent fallback or symbol translation.
- Supply UTC epoch-second, **half-open** session intervals `(start, end)`
  and optional explicit closure intervals. Every boundary is M1-aligned.
- Sessions and exclusions must each be sorted, non-overlapping and completed
  by the supplied observation time. Every exclusion must fit wholly within
  **one** declared session; cross-break exclusions and excluded minutes
  outside sessions are rejected.
- Up to 100 intervals per class and 10,000 session minutes are accepted.
  A fully excluded or absent session population is rejected, not treated as
  proof that the market is closed.
- Output is an immutable dataclass with an exact expected-minute tuple and
  deterministic SHA-256 of identity, calendar provenance, intervals and
  expected minutes. Audit recomputes the manifest to reject mutation.
- `audit_m1_receipts_against_manifest` delegates to the existing receipt
  census; missing, unexpected, conflicting, late and stale bars remain
  fail-closed. It **always** reports `expected_calendar_verified=false`,
  `live=false`, `may_execute_order=false`.

### Synthetic usage

```python
from app.expected_bar_manifest import (
    compile_expected_m1_manifest, audit_m1_receipts_against_manifest
)

t = 1790000040  # synthetic aligned UTC minute
manifest = compile_expected_m1_manifest(
    provider="fixture", symbol="XAU/USD", venue="synthetic", price_side="BID",
    calendar_id="fixture", calendar_revision="r1",
    calendar_source="operator declared bulletin",
    observed_at_utc=t + 320,
    sessions_utc=[(t, t + 120), (t + 180, t + 300)],
    exclusions_utc=[(t + 60, t + 120)],
)
assert manifest.expected_minutes == (t, t + 180, t + 240)
report = audit_m1_receipts_against_manifest([], manifest)
assert report["status"] == "REVIEW_REQUIRED"
assert report["live"] is False
```

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_expected_bar_manifest.py`

## Activation gate

A production operator must independently acquire and verify the
venue/provider's session and holiday calendar **for the exact instrument**
(including timezone/DST and ad hoc closures), version and retain it, and
ensure that the expected-bar register is independent of the feed being
checked. This module deliberately performs no timezone/DST conversion.
A configured server-owned UTC clock and a licensed TLS-authenticated provider
adapter must stamp prospective receipts and retain provider instrument IDs,
venue, price side and source response evidence. Persistence needs durable
append-only checkpoints, replay/correction handling and retention permission.

Never mark imported BID-only archives as executable quotes. Trading 212's
documented Invest/Stocks ISA API does not imply CFD API access. No provider
feed is connected by this change. Keep PR #65 draft and undeployed until
the complete release/recovery/rollback/health and licensing gates pass.
