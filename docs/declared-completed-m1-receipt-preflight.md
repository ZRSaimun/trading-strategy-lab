# Declared completed-M1 receipt preflight (offline, fail-closed)

This isolated Loop 1 audit checks **caller-declared** completed one-minute market-data receipts. It does not fetch market data, connect a broker, use credentials, charge provider credits, write prices, authorize alerts, or enable paper/live orders. It cannot authenticate the caller's timestamps, finality flags, source, venue, provider entitlements or exchange calendar.

Run synthetic tests:

```bash
cd backend
PYTHONPATH=. pytest -q tests/test_declared_completed_m1_receipts.py
```

Import `app.declared_completed_m1_receipts.audit_declared_completed_m1_receipts` and pass a nonempty list of at most 5,000 source-order receipts with **exactly** these fields: `event_id`, `provider`, `instrument`, `source_id`, `price_side` (`mid`, `bid`, or `ask`), `minute_start_utc`, `finalized_at_utc`, `received_at_utc`, `is_final`, and positive exact decimal-string `open/high/low/close`. All timestamps are UTC epoch seconds. The caller supplies a separate `as_of_utc` clock and fixed source identity. `finalized_at_utc` must be at least one minute after the start, `received_at_utc` cannot precede finalization, and neither can exceed `as_of_utc`. Source event IDs must be unique. Duplicate minutes, backward candles and observed timestamp gaps are counted; malformed identity, OHLC, timestamps or finality fail closed. The receipt stream must have nondecreasing received timestamps.

Freshness is based on **both** age since the newest candle ended and age since its receipt, plus per-record transport lag **and separate per-record finalization lag** (time from candle close to the declared finalization event). A provider may finalize an old bar immediately before delivering it, so low transport lag alone is insufficient. A newly received *old* candle cannot pass freshness. Defaults: 180-second age, 30-second transport lag and 60-second finalization lag; caller limits cannot exceed 3,600 seconds, 300 seconds and 300 seconds respectively. The finalization budget is inclusive, applies to every row (not only the newest), and a breach marks both structural cleanliness and declared freshness false. These are diagnostic thresholds, not authorization to trade or evidence of actual vendor latency. An optional strictly increasing caller-declared expected UTC-minute inventory reports missing/extra minutes, but is **not** an independently verified holiday/session register. Observed gaps do not prove an outage. The legacy `observed_gap_minutes_not_proven_missing` counts source-order forward jumps and can overcount when minutes arrive late or a range is replayed. Three additive diagnostics instead sort **distinct** observed UTC minute starts and count interior holes once: `distinct_interior_unobserved_minutes_not_proven_missing`, `distinct_interior_gap_runs_not_proven_missing`, and `largest_interior_gap_run_minutes_not_proven_missing`. A later backfill can reduce this distinct census to zero while the source-order jump remains recorded. These metrics ignore leading/trailing time outside the observed range and cannot distinguish closures/holidays from missing vendor data. They do not change the structural-cleanliness gate, freshness gate, research eligibility or order authorization. Duplicate timestamps are always quarantined, even when OHLC values match. The additive `changed_duplicate_ohlc_text_rows` counter compares each repeated minute against its **first** observed OHLC text and counts formatting differences as well as price revisions; `changed_duplicate_numeric_ohlc_rows` counts only Decimal-value differences, a subset of text changes. Thus `100.50` versus `100.500` changes the text counter but not the numeric counter. Both counters are diagnostics, never permission to accept revisions or trade. The first-seen comparison retains at most 5,000 minute-to-OHLC tuples in memory and emits no raw prices. Neither a textual match nor a numeric match establishes source authenticity. A SHA-256 over the ordered declared receipt identity/timestamp/price strings is a reproducibility checksum, not a signature, vendor authentication or license receipt. The separate `declared_audit_policy_sha256` binds provider/instrument/source/price-side, declared `as_of_utc`, all three freshness budgets, and the ordered optional expected-minute inventory (including the distinction between absent and explicitly empty). The original `receipt_inventory_sha256` remains receipt-only, so changing an expected calendar or budget cannot silently masquerade as an identical audit policy. **Compare both digests together** when reconciling results; neither digest is an independent source, signature, trusted receive clock, proof of actual session coverage or authorization to trade. No raw prices appear in the returned report.

**Declared expected-minute gap-run diagnostics (read-only):** When a caller supplies the optional expected-minute inventory, `declared_missing_expected_gap_runs` counts runs of adjacent missing UTC minutes and `largest_declared_missing_expected_gap_run_minutes` gives the longest run. A gap in the *supplied expected inventory* splits runs, so a declared session closure is not counted as missing time. `missing_declared_expected_minute_sample_utc` and `extra_declared_expected_minute_sample_utc` expose at most 12 sorted UTC epoch-minute identities each, with no prices. For an absent expected inventory all four fields are `null`; for an explicitly empty inventory counts are zero and the extra-minute sample includes observed minute identities. These are **caller-declared** session comparisons, not proof of actual market hours, vendor outage, authenticated receipts, or data rights. Existing policy/receipt fingerprints, freshness, structural gates, and trading permissions remain unchanged.

**Declared late-arrival and first-seen backfill triage (read-only):** The additive `declared_arrived_after_budget_rows` counts receipt rows delivered *strictly after* their minute close plus the caller's finalization and transport allowances. `declared_arrived_after_budget_distinct_minutes` counts unique affected minute starts; `declared_arrived_after_budget_minute_sample_utc` lists at most 12 sorted identities. At the exact composite deadline a row is not counted as late by this diagnostic, but a separate finalization or transport stage breach still fails the existing cleanliness/freshness checks. The additive `out_of_order_first_seen_minutes` counts distinct minutes whose **first** receipt appears below the highest minute previously observed in receipt order; `out_of_order_first_seen_minute_sample_utc` lists at most 12 sorted identities. Unlike the legacy adjacent backward-event counter, this high-water check identifies multiple later backfilled minutes after one newer candle. Duplicate rows never inflate the first-seen count. These metrics do not assert that a provider missed issuance, that the source timestamps are server-owned, that a calendar is authentic, or that a broker quote was executable. Neither source-order backfills nor composite lateness may be silently used as proof of outages or forward forecast outcomes. All original receipt and policy fingerprints, structural/freshness gates, and order permissions are unchanged. No prices appear in samples.

**All outputs permanently set** `source_authenticity_verified`, `server_owned_receipt_clock_verified`, `licensing_verified`, `session_calendar_verified`, `market_data_live`, `research_ready`, and `may_execute_order` to `False`. `structurally_clean` and `declared_freshness_within_budget` are descriptive only. This utility must not be used to bypass existing data eligibility or order controls.

## Activation blockers

A future real feed integration needs an owner-authorized, entitled provider/instrument/price-side mapping; independent source authenticity and permitted-use evidence; a **server-owned immutable UTC receive clock**; a provider-specific completed-bar/finality contract; authenticated expected-session/holiday/DST inventories; retention/redistribution rights; and isolated staging and recovery/rollback acceptance. Never promote Twelve Data aggregated/mid XAU/USD candles into executable broker BID/ASK or invent spreads. Trading 212's official public API currently covers **Invest and Stocks ISA**, not CFDs ([official documentation](https://docs.trading212.com/api), checked 28 Oct 2026). Twelve Data precious-metal access and redistribution depend on subscription and licensing ([Forex API v2](https://support.twelvedata.com/en/articles/12520817-forex-api-v2)); its time-series requests may consume credits ([request guide](https://support.twelvedata.com/en/articles/5620512-how-to-create-a-request)). No authenticated provider request was made by this change.


## Declared overdue versus pending missing minutes

The read-only report separately classifies **missing caller-declared expected M1 starts** by the declared finalization and transport budgets. For an expected start `m`, its declared arrival deadline is `m + 60 + max_finalization_lag_seconds + max_transport_lag_seconds` (UTC epoch seconds). A missing expected minute is **overdue** only when `as_of_utc` is strictly later than that deadline; at the exact deadline it remains **pending**. The default combined allowance after candle close is 90 seconds (60 seconds finalization + 30 seconds transport). The three additive fields are `declared_overdue_missing_expected_minutes`, `declared_pending_missing_expected_minutes`, and `overdue_declared_expected_minute_sample_utc` (up to 12 sorted UTC minute starts, no prices). Absent expected inventory yields `null` for all three; explicitly empty expected inventory yields zero counts and an empty sample.

These are **policy-relative, caller-declared missing-minute diagnostics**, not independently established provider outages, SLA violations, or a verified market-session calendar. An expected future minute can be pending. Changes to budgets alter the policy fingerprint but not the receipt fingerprint. The existing missing/extra totals, gap-run counts, structural-cleanliness and freshness gates, and permanently false source-authenticity, licensing, live, research-ready and execution flags are unchanged. No provider request or storage write is performed.


### Overdue-run triage (declared evidence only)

The additive `declared_overdue_missing_expected_gap_runs` and
`largest_declared_overdue_missing_expected_gap_run_minutes` fields group
**only overdue missing expected M1 starts** into contiguous UTC-minute runs.
Omitted expected minutes split runs; a declared session break is not silently
treated as uninterrupted trading. The sorted
`pending_declared_expected_minute_sample_utc` contains at most 12 still-pending
missing minute starts, complementing the existing overdue sample. Because the
deadline is the expected minute start plus the same fixed allowances for every
minute, overdue starts form a sorted prefix of the missing population. The
report never invents a provider outage or assumes future expected minutes
have been delivered. All three fields are `null` when no expected inventory
was supplied, and 0/0/[] when an explicitly empty inventory was supplied.

This is an offline diagnostic for coordinating delayed forecast issuance and
data-quality investigations. The expected calendar, `as_of_utc`, finality and
receipt times remain **caller-declared**. Neither these fields nor clean
results authorize alerts, live market-data claims, paper fills or real orders.


### First-seen lateness versus late replay (declared evidence only)

A repeated M1 minute can arrive after the declared delivery budget even if
the **first** receipt of that minute arrived on time. Treating every late
duplicate as a missed initial issuance would overstate source-feed gaps.
The additive `declared_first_seen_after_budget_minutes` counts distinct minute
starts whose *first* observation arrived strictly after minute close plus
declared finalization and transport allowances. Its corresponding
`declared_first_seen_after_budget_minute_sample_utc` contains at most 12
sorted UTC minute starts. The separate
`declared_late_first_seen_backfill_minutes` and
`declared_late_first_seen_backfill_minute_sample_utc` count/sample only
those late first observations that were also first-seen out-of-order
backfills below the previous candle-start high-water mark.

These populations are subsets of the existing late-distinct and first-seen
backfill counts respectively. A duplicate that is late cannot retroactively
make an on-time first observation late. The exact composite deadline remains
inclusive (not late), while individual transport/finalization stage breaches
continue to fail the pre-existing cleanliness/freshness gates. These metrics
are **caller-declared**; they do not prove provider outages, independent
receipt custody, session coverage, data entitlements, executable quotes or
forecast-delivery failures. The original receipt/policy digests and all
permanently false authorization flags are unchanged. No prices are returned.
