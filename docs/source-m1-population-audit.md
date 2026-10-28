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

Before using this on real archives, separately verify original compressed ZIP SHA-256 and read-only database snapshot identity, confirm the documented provider timestamp convention and offset (including DST), independently parse and compare exact original decimal OHLC values and duplicate-row identity, verify source rights, and freeze the aggregation policy and expected-bar calendar. The Loop 2 handoff on 28 Oct 2026 reported 11 historical datasets with 60 extra source rows each and a combined 44 complete-M15-bar raw-versus-deduplicated discrepancy; those counts are **not** independently reproduced by this helper until genuine source and store timestamp lists are supplied.

Run synthetic tests:

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_source_m1_population_audit.py
```
