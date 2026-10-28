# Declared M1 calendar reconciliation (read-only research helper)

This offline, pure-Python helper compares an observed list of UTC minute-open epochs with an **explicitly declared** expected-minute inventory. It does not generate market sessions, guess holidays, fill gaps, modify candles, call providers, read credentials, write a database, or execute trades. It is not wired to the live site or automatic imports.

Use only for review of a *separately obtained* expected-minute inventory. An arbitrary list, even with a stable SHA-256, **does not establish** an independently verified market calendar. The result always sets `independent_calendar_verified=false`, `provider_entitlement_verified=false`, `source_authenticity_verified=false`, `quote_side_verified=false`, `missing_market_data_proven=false`, `live=false`, and `may_execute_order=false`.

## Offline example

```python
from app.declared_m1_calendar_reconciliation import audit_declared_m1_coverage

# Synthetic UTC minute epochs, not vendor quotes or a genuine market schedule.
expected = [1790000040, 1790000100, 1790000160]
observed = [1790000040, 1790000160]
result = audit_declared_m1_coverage(
    observed, expected, declaration_id="synthetic-review-v1",
)
assert result["unobserved_declared_minutes"] == 1
assert result["missing_market_data_proven"] is False
```

Inputs are strictly increasing, unique, nonnegative, minute-aligned UTC integer epoch lists, bounded to 100,000 minutes each. The expected list must be nonempty; an empty observed list is permitted to report complete noncoverage. Declaration identifiers and sample sizes are bounded. Invalid lists, bools, out-of-range dates, duplicates and unsorted timestamps fail closed. A two-pointer comparison counts matched declared minutes, declared-but-unobserved minutes, and observed-but-undeclared minutes, with at most 20 timestamp examples of each. The deterministic hashes fingerprint the supplied timestamp lists only; they are **not** vendor signatures or license evidence. No OHLC prices are accepted or emitted.

A weekend omitted from the declaration is not counted missing. Conversely, an incorrect declaration can falsely mark an actual trading minute as outside session or a holiday as missing. Do not convert these counts into a completeness claim until the independent provider/venue/instrument calendar, timezone and DST semantics, holiday exceptions, source timestamp convention, and entitlement have been reviewed. The existing `assess_completed_m1` audit remains observed-only; this helper is not a replacement or a production quality gate.

Run offline regressions:

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_declared_m1_calendar_reconciliation.py
```

## Activation blockers

A future authorized staging integration needs a licensed XAU/USD minute source with documented price side, immutable receipt timestamps and finality, an independently registered and versioned expected-bar calendar, calendar rights, gap and staleness thresholds, and replay/rollback verification. Neither a static historical BID candle nor a declared calendar list is a current executable two-sided CFD quote. No broker, paid feed, live market data or order path is activated by this module.
