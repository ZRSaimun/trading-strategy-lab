# Offline economic-calendar revision as-of guard

`app.offline_event_asof_guard.audit_declared_event_asof` provides a disconnected, deterministic research-only fence for historical economic-calendar **revision visibility**. It does not call Forex Factory, Investing.com, the Federal Reserve, brokers, or any external API. It does not authenticate source timestamps or prove any tradeable edge.

Supply bounded, closed-schema records with event ID, consecutive revision number, `schedule` or `result` kind, minute-aligned UTC scheduled/publication/observation clocks, optional decimal-string forecast, and actual only for result revisions. Revisions are ordered by revision number and require strictly increasing observation clocks; a result cannot be declared released before its scheduled event time. A result may only be included in a decision snapshot after its observation clock and event time have passed. Future revisions are ignored in historical snapshots, not used to revise earlier knowledge. The output is sorted and SHA-256 digested for reproducibility; this hash is **not an external time anchor or proof of authenticity**. The visible-revision count excludes future revisions to avoid leaking even metadata from the future.

This intentionally omits event descriptions, units, surprise calculations, calendar impact categories, revision-time provenance signatures, and trading signals. A schedule-only snapshot does not imply a particular direction or price move. Multiple provider feeds must not be silently combined; the caller must use a source-isolated event inventory. Real event rescheduling, corrected results, early releases, and finer-than-minute observations require separately reviewed semantics. An observation clock supplied by the same backtest cannot establish an independent point-in-time record. For an honest backtest, independently authenticate the original event feed, its revision history and receipt timestamps, then freeze strategy rules and an untouched chronological holdout. Include bid/ask spreads, slippage, commission, financing and FX where applicable; never equate a backtest signal with a broker-executable order.

Synthetic regression: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_offline_event_asof_guard.py`. No production route, data, credentials, or broker order is changed.

## 29 October 2026: causal integrity hardening

Result revisions must retain the latest pre-result schedule timestamp and forecast; they cannot silently rewrite the historical announcement time or pre-release consensus when computing later research snapshots. A genuine corrected schedule or forecast after the release needs an explicitly reviewed, separately typed correction model rather than being smuggled into a result record. Decimal canonicalization now uses exact fixed-point formatting rather than ambient-context `Decimal.normalize()`, preserving up to 30 declared fractional places without silent rounding. Extreme exponents are rejected. These restrictions intentionally fail closed on unmodelled vendor conventions and do not authenticate caller-declared clocks or values.

## 29 October 2026: pre-release consensus timing fence

A schedule/forecast observation must be **strictly earlier** than its own scheduled announcement time. Any subsequent schedule revision must also have been observed strictly before the **previously scheduled** event time. This prevents a post-release calendar update from being used as if it were the original pre-news forecast, and prevents a late postponement from silently erasing an earlier expected release. A revision observed exactly at the announcement minute fails closed because minute-granular receipts cannot establish pre-release ordering. Legitimate late cancellations, postponements after the old event time, and sub-minute vendor receipts require a separate explicitly reviewed event model; they are **not** silently accepted here. Six synthetic regression cases cover these boundaries and a valid advance reschedule. The guard still relies on caller-declared timestamps, not authenticated receipt provenance, and provides no trade authorization or profitability evidence.

## 29 October 2026: decision-minute receipt ambiguity

**Fail-closed as-of visibility:** all declared observation clocks are only minute-precise. A record stamped at the same minute as the historical decision cannot be proven to have arrived before that decision. Both the event snapshot and `visible_revision_count` therefore include only records with `observed_utc < decision_utc` (strict inequality), even if `published_utc` and `scheduled_utc` are earlier. A result observed at 18:00 UTC first becomes eligible at the 18:01 UTC decision boundary, never at 18:00. The same rule applies to schedule revisions and first schedule visibility. This is conservative rather than a claim of exact intraminute sequencing. If authenticated sub-minute event receipt and decision timestamps become available, model those clocks separately and test them before relaxing this fence. The synthetic regressions cover schedule/result exact-minute exclusions, revision counts, future-snapshot invariance, and next-minute availability. No live data or trading authority is introduced.


## 29 October 2026: source- and cutoff-bound research envelope

The existing `visible_snapshot_sha256` remains an event-content-only digest for backward compatibility. Identical visible event lists can have the same digest even when they come from different declared sources or decision times. It must not be used as a unique audit identity.

A new additive `research_envelope_schema_version: 1` and `research_envelope_sha256` bind the **declared** `source_id`, UTC decision cutoff, visible revision count and visible events in sorted-key, compact, ASCII-escaped JSON. The digest is stable under row ordering and future invisible revisions; it changes when the declared source or cutoff changes, including empty-event reports. This is useful for preventing accidental research-artifact misattribution across providers, decision cutoffs and folds. It is **not** a digital signature, independent timestamp, verified source lineage, licensed feed attestation or authorization to trade. A dishonest caller can still fabricate all fields; protect the original vendor receipt and immutable archive separately.

Five synthetic regressions check source binding, decision binding, future-revision/order invariance, independently recomputed canonical digest and empty-event source binding. No calendar feed, production API, order path or protected holdout was added.


## 29 October 2026: full-visible-history v2 audit identity

**Compatibility:** The existing `visible_snapshot_sha256` and `research_envelope_sha256` (v1) remain unchanged. They encode the latest visible event per ID plus a revision count, not every intermediate revision. Consequently two distinct pre-decision consensus histories with the same final event and the same number of revisions can have identical v1 hashes. **Do not interpret v1 as a complete historical revision lineage identifier.**

New additive fields `visible_revision_history_sha256`, `research_envelope_v2_schema_version: 2`, and `research_envelope_v2_sha256` address this narrow reproducibility problem. The history digest includes **every visible normalized revision**, ordered by event ID then revision, including intermediate pre-decision schedule forecasts and eligible results. The v2 envelope binds this history digest, declared source ID, decision UTC, visible revision count and final visible events. It excludes records with `observed_utc >= decision_utc`, so later revisions and exact-decision-minute receipts cannot contaminate earlier audit identities. Hashes use sorted-key, compact, ASCII-escaped JSON and SHA-256.

Use v2 for **new offline research artifacts** requiring a declared full-visible-revision lineage; retain v1 only for compatibility. Synthetic tests compare histories with identical latest visible events/counts but different intermediate forecasts, prove future and same-minute exclusion, verify ordering and independent canonical reconstruction, and cover empty histories. These digests remain self-reported checksums, **not** signatures, vendor receipt attestations, evidence of complete vendor revision inventories, executable quotes, or trade authorization. No production integration, broker path, external feed, costed backtest, or holdout validation is introduced.


## 29 October 2026: Declared as-of news-window census

The additive `audit_declared_event_window(revisions, *, decision_utc, source_id, before_minutes=30, after_minutes=15)` performs a **read-only, offline research census** of visible scheduled economic announcements within a symmetric-or-asymmetric event proximity interval. It calls the strict as-of revision guard first; future calendar changes, exact-decision-minute receipts and post-release forecast rewrites are never used to determine a historical event window. A rescheduled event moves its research window **only after** the new schedule was observed before the decision minute. Each matched event records signed `minutes_until_event` (positive before, zero at event, negative after). Boundaries are inclusive, and both integer widths must be 0–1440 minutes; bools, floats and negative values are rejected.

The returned `within_declared_event_window` means **only** that at least one *declared and visible* event falls inside the supplied interval. A false value is **not** proof of an event-free market, safe trading conditions or sufficient source coverage. In particular, an empty or incomplete calendar can produce zero matches. The output explicitly sets `coverage_verified=False`, `authenticated_calendar=False`, `trade_authorized=False`, and `research_only=True` in every case. Never use the false value to bypass a production news risk gate or to authorize a real-money or demo order. The scope is **source-isolated**; multiple providers cannot be silently merged.

`window_audit_sha256` deterministically binds the as-of v2 research envelope, the two window widths and matched events. It is a reproducibility checksum, not vendor receipt attestation. Synthetic tests cover inclusive pre/post windows, minute-boundary exclusion, later schedule revisions, result observations, empty inventories, parameter rejection, row-order stability, and source-bound hashing. No impact classification, event completeness proof, live feed, strategy performance, executable quote, broker connection or production integration is supplied.

Example research-only usage:

```python
from app.offline_event_asof_guard import audit_declared_event_window

report = audit_declared_event_window(
    declared_revisions,
    decision_utc="2026-10-28T17:30:00Z",
    source_id="synthetic-calendar",
    before_minutes=30,
    after_minutes=15,
)
# report["within_declared_event_window"] is NOT a trade clearance.
```


## 29 October 2026: Declared raw economic surprise audit

`audit_declared_surprise_asof(revisions, *, decision_utc, source_id)` is an
**offline, source-isolated research helper**. It uses the strict calendar
as-of snapshot and computes `actual - forecast` only after the actual result
has been observed **strictly before** the decision minute and a declared
forecast exists. Missing results return `ACTUAL_NOT_VISIBLE`; a visible
result without forecast returns `FORECAST_MISSING`. Neither case fabricates
a zero surprise. Both values must be declared decimal strings and are
subtracted with sufficient Decimal precision to avoid 28-digit rounding.

The `DECLARED_RAW_DIFFERENCE` status is not a normalized surprise, market
direction, magnitude significance, event-impact score, or trading signal.
The code has no event units, scale, consensus sample, previous-release
revision history authentication, source completeness or independently
timestamped receipts. Differences across unlike indicators must not be
ranked or compared. The output always marks
`authenticated_calendar=False`, `coverage_verified=False`,
`comparable_units_verified=False`, `trade_authorized=False`, and
`research_only=True`. A nonzero declared difference never authorizes
a paper or live order.

The deterministic `surprise_audit_sha256` binds observations to the
source/cutoff/full-visible-revision v2 envelope. It is a self-declared
reproducibility checksum, not source attestation. Synthetic regression
cases cover strict receipt boundaries, missing forecasts, exact 30-place
arithmetic, negative/zero results, future-data noninterference, source
identity, ordering and independently recomputed digest. No external
calendar data, protected historical holdout, executable-cost evaluation,
production integration or broker connection was added.



## 29 October 2026: First-release versus corrected-result as-of census

The additive audit_declared_result_corrections_asof helper is disconnected and
research-only. A later correction to an economic announcement cannot be
misrepresented as the first result available to a historical news trader.
The helper validates the entire declared revision chain first, then includes
only results observed strictly before the historical decision minute. It
reports first/latest as-of-visible actual, receipt times and revision numbers,
raw first/latest surprise versus the pre-release forecast, exact net actual
change, and the count of changed adjacent result revisions. Reversion to the
original actual still records intermediate changes; repeated identical actual
is a revision but not a price-value change. Missing result and forecast stay
null rather than becoming fabricated zero surprise.

The versioned result_correction_audit_sha256 binds the full-visible-revision
v2 research envelope and deterministic observations. All outputs explicitly
deny calendar authentication, coverage verification, cross-indicator unit
comparability and trading permission. The digest is NOT independent vendor
receipt provenance or a source-completeness attestation. Ten synthetic
regression functions test exact-minute receipt exclusion, future correction
noninterference, correction/reversion counting, precision, source/cutoff
binding, deterministic ordering and malformed future records.

No historical calendar or market archive replay, executable BID/ASK spread,
slippage, financing, independent holdout, production route, paid feed or broker
order is introduced. Authenticate vendor receipt times and join source-isolated
market candles before making any costed trading-performance claim.
