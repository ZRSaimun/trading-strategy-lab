# Declared fixed-offset M15 bucket anchor audit (offline, read-only)

The Python function app.declared_m15_bucket_anchor_audit.audit_declared_m15_bucket_anchors compares **exact M15 UTC bucket identities** implied by caller-declared source wall-clock M1 labels against a separately supplied UTC M1 anchor inventory. It is an additive, disconnected structural diagnostic for Loop 1/Loop 2 historical-data reconciliation. It does not read archives or databases, call providers, choose a clock offset, modify data, enable a strategy, or authorize an order.

## Inputs and semantics

- **source_wall_minutes**: original source-order M1 wall-clock labels, represented by the epoch seconds their **naive wall fields would have if interpreted as UTC**. Duplicate rows and backward jumps are accepted as observations. Labels must be minute-aligned and bounded.
- **anchor_utc_minutes**: **caller-supplied** sorted unique UTC M1 starts. The caller must separately establish independent custody, provenance, timebase, and permitted usage. This list is not an authenticated market calendar.
- **offset_candidates_minutes**: 1–32 distinct fixed offsets, local minus UTC, in 15-minute increments within -840..840. Fixed EST corresponds to -300 and implies UTC = wall + 300 minutes. This does not handle DST-local ambiguous or nonexistent times.
- **source_id**: bounded audit identifier, not proof of archive identity.

A *complete source M15 bucket* contains all 15 distinct aligned M1 starts. A *replay-free complete bucket* additionally contains exactly 15 original source rows (no repeated minute). An *anchor-complete bucket* contains all 15 UTC minute starts. A *matched clean bucket* is a replay-free complete source bucket whose shifted UTC start **exactly matches** an anchor-complete bucket. Counts are **structural only**: source-order contiguity, independent source authenticity, bid/ask, session/holiday eligibility and price accuracy are not established.

## Synthetic usage (no real market observations)

    from app.declared_m15_bucket_anchor_audit import audit_declared_m15_bucket_anchors

    wall = [1_790_000_100 + i * 60 for i in range(15)]
    anchor = [minute + 300 * 60 for minute in wall]
    report = audit_declared_m15_bucket_anchors(
        wall, anchor, source_id="synthetic:histdata", offset_candidates_minutes=[-300, 0]
    )
    assert report["candidate_results"][0]["anchor_matched_replay_free_complete_m15_buckets"] == 1
    assert report["clock_offset_selected"] is False
    assert report["may_execute_order"] is False

The report includes total source M15 buckets, complete, replay-free, replay-touched and incomplete bucket counts; anchor-complete counts; and per-candidate exact bucket intersections, differences, SHA-256 fingerprints and at most eight UTC bucket starts. The digest is SHA-256 of ASCII prefix DECLARED_ANCHOR_MATCHED_CLEAN_M15_BUCKET_STARTS_V1 followed by a newline and each **ascending** matched UTC bucket-start epoch plus newline. It is a comparison checksum, not a signature, authentication or licensing evidence. A matching count with a different fingerprint means different bucket identities. An empty match also has a deterministic fingerprint. No prices or credentials appear in the report.

Inputs are limited to 100,000 rows per inventory; candidate offsets are capped at 32. Invalid, unsorted anchor, duplicate anchor, unaligned, out-of-range, ambiguous or truthy-non-integer values fail closed. All results keep clock_offset_selected, clock_offset_verified, anchor_independence_verified, source_authenticity_verified, market_calendar_verified, licensing_verified, research_ready, live and may_execute_order false. A unique 100% match **does not** establish a correct clock convention or trading eligibility.

To reconcile the previously observed 660 duplicate M1 rows and 44 additional source-order M15 windows across 11 archives, freeze original archive digests, extract privately audited wall labels, obtain independently documented UTC anchors, compare candidate fingerprints with Loop 2, and quarantine replay-touched or ambiguous windows. Do not use a source-order 15-row aggregation as a valid M15 bar when minutes repeat. Do not treat missing anchor minutes as verified market outages without a separately authenticated expected-session inventory.

Synthetic test command (no network or provider credits):

    cd backend
    PYTHONPATH=. pytest -q tests/test_declared_m15_bucket_anchor_audit.py

Provider constraints (reviewed 28 October 2026): [HistData specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/) describes fixed EST without DST and BID-based M1 candles; it does not authenticate any uploaded ZIP. [Trading 212 public API](https://docs.trading212.com/api) is documented for Invest and Stocks ISA, not CFDs. Entitlements and live execution remain separate and disabled.


## Original source-row M15 contiguity (additive diagnostic)

Distinct-minute completeness can conceal shuffled or interleaved original M1 rows. The existing replay-free and anchor-matched M15 counts remain **distinct-minute structural counts** for compatibility; they do not prove original source-row contiguity.

The audit now separately reports `source_order_contiguous_replay_free_complete_m15_buckets` and `source_wall_replay_free_complete_but_noncontiguous_m15_buckets`. For each declared offset, `anchor_matched_source_order_contiguous_clean_m15_buckets` counts buckets that are complete, globally untouched by repeated source-minute labels, occur as 15 consecutive ascending source rows aligned to a quarter hour, and have a matching anchor-complete UTC bucket. It also provides an outside-anchor count, a distinct domain-separated SHA-256 fingerprint (`DECLARED_ANCHOR_SOURCE_ORDER_CLEAN_M15_BUCKET_STARTS_V1` plus newline-separated ascending UTC starts) and up to eight exact UTC bucket-start samples.

This is **per-bucket** row-order contiguity, not global chronological verification. Entire M15 blocks may be reordered and still count. Independently verify global backward jumps, source identity, original price parity, timestamp convention, UTC anchor custody, trading calendars, and rights before research. The new structural metric never selects an offset or enables research, live data, or orders. Seven synthetic regressions cover shuffled/interleaved rows, block reordering, repeated minutes, offset mapping, fingerprints, and sample limits.
