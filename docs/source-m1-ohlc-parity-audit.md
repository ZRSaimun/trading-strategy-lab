# Source-order M1 OHLC parity preflight (offline only)

`app.source_m1_ohlc_parity_audit.audit_source_m1_ohlc_parity` compares **caller-provided** raw source-order M1 `(utc_epoch, open, high, low, close)` tuples with a caller-provided **strictly sorted, unique** frozen stored-row snapshot. It does not read archives or databases, connect to market providers, fetch quotes, write prices, infer a market calendar or change any research/execution gate. It reports **no price values**.

The helper checks exact decimal numeric equality (so `1.0` and `1.00` compare equal), repeated identical and conflicting source rows, backward timestamps, missing and extra stored minutes, and stored OHLC mismatches against the first source occurrence. All repeated source minutes are quarantined, **even if their OHLC matches**. Source order and stored canonical numeric tuples have separate SHA-256 fingerprints; neither authenticates original compressed ZIP bytes, a broker, a database snapshot, nor source licensing. A conflict after the first source occurrence is separately reported and cannot be silently corrected by choosing the matching row.

```python
from app.source_m1_ohlc_parity_audit import audit_source_m1_ohlc_parity

t = 1790000100  # synthetic UTC quarter-hour boundary
source = [(t, "1.0", "2", "0.5", "1.5"), (t, "1.1", "2", "0.5", "1.5")]
stored = [(t, "1.0", "2", "0.5", "1.5")]
report = audit_source_m1_ohlc_parity(source, stored, source_id="synthetic:v1")
assert report["source_conflicting_repeated_rows"] == 1
assert report["result"] == "QUARANTINE_REQUIRED"
```

Both inputs must be nonempty Python lists with at most 100,000 tuples each. Each epoch must be a non-boolean, UTC minute-aligned integer in the supported range; prices must be plain decimal **strings**, with at most 15 integer digits and 12 fractional digits, and internally consistent OHLC bounds. No binary floats, exponent notation, `NaN` or infinities are accepted. Signed values are permitted for generic historical futures, without claiming any specific negative price is authentic. A bound or malformed input raises `ValueError` rather than returning a successful report. Samples include UTC timestamps and source row ordinals only (max 20); `sample_limit=0` preserves counts.

`EXACT_DECIMAL_PARITY_ONLY_UNVERIFIED` **does not** approve historical research, market-data freshness, paper fills, alerts, or real orders: `research_ready`, `live` and `may_execute_order` always remain false. Separately establish original archive SHA-256, source rights and authenticity, timestamp/UTC offset/DST convention, immutable snapshot identity, provider/venue/price-side, independently verified expected session/holiday calendar, and any required original source-row vs M15 aggregation policy. This audit does not reproduce the previously reported 11-dataset / 44-window discrepancy without the original source and stored rows.

Synthetic tests: `cd backend && PYTHONPATH=. pytest -q tests/test_source_m1_ohlc_parity_audit.py`.
