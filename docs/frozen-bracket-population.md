# Frozen M1 bracket population completeness gate (offline, Loop 2)

`backend/app/frozen_bracket_population.py` is an offline **research-integrity** helper, not a live strategy, optimizer, broker adapter, order endpoint, market-data import, or deployment change. It wraps the existing `ohlc_bracket_uncertainty.audit_paths` evaluator. It prevents silently omitting losing, ambiguous or censored **registered** signals when reporting historical M1 bracket outcomes.

## Freeze before viewing outcomes

Record an independently retained `m1-bracket-population-v1` manifest containing exactly: `protocol`, `source`, `eligible_signals`, `excluded_signals`. `source` has exact `instrument`, `provider`, `venue`, `archive_sha256`, `price_side` (`BID`, `ASK` or `MID`) and one `horizon_minutes` (1–1440). Every eligible row contains only `path_id`, UTC-minute `signal_at`, `direction`, `entry`, `stop`, `target` as pre-outcome facts. Excluded rows contain only `path_id`, `signal_at` and a **pre-signal** reason from the fixed allowed set (`PRE_SIGNAL_DATA_GAP`, `INVALID_PRE_SIGNAL_CONTEXT`, `OUTSIDE_FROZEN_ELIGIBILITY_WINDOW`, `SOURCE_UNAVAILABLE_BEFORE_SIGNAL`). No outcome labels, future prices or realized returns are allowed in the manifest. Eligible and excluded IDs and signal minutes cannot overlap.

Compute `fingerprint_population_manifest(manifest)` and retain its 64-character SHA-256 **outside this invocation before the outcome period**. Canonical serialization sorts rows by signal time and ID; membership, price parameters, source identity and exclusion reasons affect the digest. `audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)` rejects digest mismatch, omitted or extra outcomes, duplicate IDs, changes to any frozen field or source identity, and altered next-minute entry clocks. It passes the complete eligible set to the existing Decimal M1 stop/target bounds and fixed additional 0/5/10/20 bps illustrative cost scenarios. Censored observations remain censored. Output ordering is deterministic.

Any declared exclusions are counted by reason, and **population mean estimates are withheld** with `UNVERIFIED_EXCLUSIONS`, even if the remaining eligible sample is large. Without exclusions, the underlying evaluator still withholds means for censored samples or insufficient size/week coverage. Even an otherwise clean result is only `DESCRIPTIVE_BOUNDS_ONLY`, never a profitable or executable signal.

## Limitations

A digest supplied together with its manifest does **not** prove the manifest was frozen before outcomes, nor that the upstream generator registered every eligible signal. `complete_against_supplied_manifest=true` means only that all *declared* eligible IDs are present. The gate does not independently authenticate archives, timestamp/UTC/DST conventions, source rights, spreads, slippage, borrow/funding, commissions, signal causality, eligibility/exclusion legitimacy, holdout independence or broker fills. It cannot remove lookahead introduced by an upstream signal generator. Source archive SHA-256 is an identity, not proof of authenticity. All external evidence flags remain false. Never optimize the frozen registry using holdout outcomes, cherry-pick optimistic bounds, or submit real-money orders.

### Synthetic-only verification

```bash
cd backend
PYTHONPATH=. python -m pytest -q tests/test_frozen_bracket_population.py
```

**Handoff:** PR #24 must freeze CRT/ICT signal eligibility and entry/stop/target/horizon *before* outcome evaluation. PR #29 must independently enforce source-isolated chronological holdout membership and preserve excluded observations. PRs #41/#43 must not promote quarantined HistData archives merely because this supplied manifest matches its outcomes. PR #25 paper fills require authenticated, timestamped executable quotes and broker-specific cost reconciliation. No private archive prices or secrets belong in the Git repository.
