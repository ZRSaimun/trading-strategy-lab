# Source-order M1 population preflight (offline only)

`app.source_m1_population_audit.audit_source_m1_population` compares **caller-provided source-order M1 timestamp epochs** with **caller-provided stored strictly increasing unique M1 epochs**. It is a pure, read-only, timestamp-only structural census. It does not read ZIPs, query SQLite/PostgreSQL, access provider APIs, infer source timezones, import prices, change `READY` status, or execute trades. It cannot independently establish provider identity, source authenticity, data rights, executable bid/ask, OHLC parity or market session coverage.

This addresses a research integrity concern: deduplicating historical M1 rows may preserve all distinct minute timestamps while changing the population of complete **source-order contiguous** M15 windows. A repeated 60-minute source block can add four complete M15 windows even when the stored unique-minute timestamp set matches the source exactly. Do **not** treat identical distinct-minute sets or archive SHA matches as full historical-engine parity.

```python
from app.source_m1_population_audit import audit_source_m1_population

# Synthetic example, not vendor data. UTC quarter-hour aligned.
t = 1790000100
original = [t + 60 * i for i in range(120)]
raw = original[:90] + original[15:75] + original[90:]
report = audit_source_m1_population(raw, original, source_id="synthetic:v1")
assert report["source_repeated_rows"] == 60
assert report["source_minus_stored_complete_m15_windows"] == 4
assert report["research_ready"] is False
```

A complete M15 window here means 15 consecutive, source-order, minute-aligned rows beginning at a UTC quarter hour. Repeated complete windows are counted separately; incomplete, discontinuous or misaligned windows are not counted. This is **not** a price aggregation, exchange-calendar check or proof that any M15 bar is tradeable. The stored census uses the same rule on sorted unique epochs. The result reports counts, first/last repeat ordinals, bounded repeated-minute and repeated-window examples, two different scoped SHA-256 timestamp-list fingerprints, missing/extra stored minutes and the signed M15 population delta. It deliberately reports no prices.

The `QUARANTINE_REQUIRED` result is issued if source repeats, backward jumps, source/store timestamp differences, or an M15 count difference are observed. `STRUCTURAL_PARITY_ONLY_UNVERIFIED` is never an approval for research, live data or orders; the `research_ready`, `live` and `may_execute_order` flags always remain false. The helper does not automatically downgrade a production database state.

Inputs must be nonempty Python lists of at most 1,000,000 UTC-aligned integer epochs per list. Stored epochs must be strictly increasing and unique. Invalid types (including bool), timestamps, resource limits, IDs or sample limits fail closed. Samples are bounded to 20; full counts are still computed when `sample_limit=0`.

Before using this on real archives, separately verify original compressed ZIP SHA-256 and read-only database snapshot identity, confirm the documented provider timestamp convention and offset (including DST), independently parse and compare exact original decimal OHLC values and duplicate-row identity, verify source rights, and freeze the aggregation policy and expected-bar calendar. The Loop 2 handoff on 28 Oct 2026 reported 11 historical datasets with 60 extra source rows each and a combined 44 complete-M15-bar raw-versus-deduplicated discrepancy. An independent offline scan of the owner's original 11 ZIPs and frozen read-only SQLite research snapshot on 28 Oct 2026 **reproduced all 660 repeated rows and the +44 raw-order M15 window delta**, with zero admitted source-line, member, timestamp or FLOAT-converted OHLC mismatches. See [independent archive/SQLite reproduction](independent-archive-sqlite-reproduction-20261028.md) for dataset counts, snapshot SHA-256 and important DST, licensing and exact-decimal limitations. This pure helper itself still does not read original archives or databases.

Run synthetic tests:

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_source_m1_population_audit.py
```

## Repeated-row run diagnostics

The audit also counts **consecutive source-order rows whose UTC minute has already appeared earlier**. It reports `source_repeated_row_run_count`, `source_longest_repeated_row_run`, and up to `sample_limit` first/last ordinal and UTC-minute examples. A 60-row replayed block yields one 60-row run; separated duplicate clusters yield separate runs. A run is contiguous **in row order**, not necessarily continuous in market time, and cannot establish whether duplicated rows have matching OHLC or a legitimate exchange session. Counters remain available with samples disabled; these diagnostics never override quarantine or research/market-data permissions.

## M15 bucket identity and replay contamination (read-only)

Aggregate complete-window counts alone can conceal **different UTC M15 bucket identities**. The audit now separately counts complete source-order M15 buckets absent from the stored complete-bucket set, and complete stored buckets absent from the source-order complete-bucket set. Both directions include bounded UTC-start samples. A zero net window delta is **not** proof of identical eligible research populations.

It also identifies every **complete stored M15 bucket containing any minute timestamp repeated anywhere in the source-order inventory**, even if the replay occurs nonadjacently and even if the repeated prices match. The `stored_complete_m15_buckets_touched_by_repeated_source_minutes` count and bounded `stored_complete_m15_replayed_source_bucket_samples_utc` help quantify candidates for a future strict duplicate-row quarantine policy. The `common_complete_m15_buckets_without_repeated_source_minutes` count is only a **structural intersection** of complete source-order and stored windows with no repeated minute timestamps; it is **not an approval** to backtest, execute, or declare source/calendar authenticity. Incomplete stored M15 buckets are excluded from the replay-touched complete-bucket count, but duplicate M1 timestamps still trigger global quarantine.

All new diagnostics are deterministic and timestamp-only. They do not read prices, prove matching OHLC, authenticate original archives, establish licensing or source clock conventions, decide whether to aggregate duplicates, or remove the global `QUARANTINE_REQUIRED` result. Counts are computed over the full bounded inventory even when `sample_limit=0`. Existing callers retain the prior result keys.

## Contiguous clean M15 structural runs and scoped fingerprints

The offline audit additionally segments the **intersection of complete source-order and stored M15 buckets that are untouched by any repeated source M1 minute** into consecutive UTC 15-minute runs. It reports `common_clean_m15_contiguous_run_count`, `common_clean_m15_longest_contiguous_run_buckets`, and at most `sample_limit` bounded first/last UTC bucket and bar-count samples. Gaps of even one M15 bucket split runs. With `sample_limit=0`, counts are still computed and no run timestamps are emitted. These are *structural* runs, not certified market sessions or a backtest admission policy; missing session calendars, price parity and data licensing still block research approval.

Three domain-separated SHA-256 digests bind caller-declared sorted sets: `source_repeated_minute_set_sha256` (`REPEATED_SOURCE_M1_SET_V1`), `stored_replay_touched_complete_m15_set_sha256` (`STORED_REPLAY_TOUCHED_M15_SET_V1`), and `common_clean_complete_m15_set_sha256` (`COMMON_CLEAN_M15_SET_V1`). Each hashes the scope followed by newline-separated integer UTC epoch timestamps; the empty set has a deterministic digest. This lets an independent offline Loop 2 tool compare *privately reconstructed* populations without publishing complete licensed timestamp inventories. **These hashes are not ZIP signatures, independent provenance, authenticated timestamps, authorization to distribute data, or proof that an OHLC/strategy cohort is safe.** Preserve the original ZIP SHA and private timestamp-conversion evidence separately.

Synthetic regressions:

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_source_m1_population_audit.py tests/test_source_m1_population_clean_runs.py
```

All outputs remain read-only, bounded, timestamp-only and `research_ready=False`. No live feed or execution route is enabled.
