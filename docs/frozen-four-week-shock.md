# Frozen four-UTC-week shock stress — offline research only

`backend/app/frozen_four_week_shock.py` adds a deterministic, **post-outcome** concentration and adverse-window sensitivity diagnostic for the complete frozen M1 bracket population. It is **not** a trading strategy, statistical confidence interval, prospective prediction, or broker-execution component.

## Protocol

Call `audit_frozen_four_week_shock(manifest, paths, expected_manifest_sha256)`. The existing `audit_frozen_bracket_population` gate first verifies the caller-supplied source/manifest SHA-256, exact one-to-one frozen path identity, entry clocks, unchanged bracket fields, and complete path evaluation. A matching self-supplied SHA-256 is only a consistency check: it is **not** independent evidence of pre-outcome registration, source authenticity, license rights, or an untouched holdout.

All eligible paths are assigned to their **signal's UTC Monday-start calendar week**, not to their outcome/exit week. The calendar is expanded continuously from the first to the last signal, retaining every **zero-signal week**. Each consecutive **four-calendar-week** window is evaluated once. Windows are not selected as tradable regimes or used to remove signals.

For each existing additional round-trip cost assumption **0/5/10/20 basis points**, the auditor independently sums exact Decimal lower and upper net-R bounds for all paths and reports:

- Total lower/upper additive R, worst and best consecutive four-week lower/upper sums.
- Total additive R after hypothetically removing the *most favorable* four-week window under each respective bound (a post-hoc fragility diagnostic, **never** permission to remove those weeks).
- Active and zero-signal UTC calendar weeks, most populated four-week window and its signal count.

Different windows can maximize the lower and upper bounds. The bounds preserve intrabar stop/target ambiguity; they are not compounded account equity, margin-adjusted returns, or actual executable fills. The four-week duration is fixed before inspecting outcomes and is **not** optimized to historical returns.

## Fail-closed gates

No return statistics are produced when the upstream frozen population has exclusions, censored paths, incomplete identity, unexpected cost scenario schemas, fewer than 30 eligible paths, fewer than 12 active UTC weeks, or a calendar span shorter than 16 or longer than 520 weeks. Changed manifest hashes, duplicated paths, changed source identities, and invalid entry clocks are rejected by the upstream audit. Missing trading-session calendars are **not** invented; a zero-signal calendar week is not proof of missing vendor data.

This is a retrospective stress diagnostic, not a calibrated confidence interval or a causal market-regime filter. No claim is made about independence between trades, source completeness, genuine bid/ask spreads, slippage, commissions, CFD financing, margin, licensing, timestamp correctness, broker fills, or profitability. It does not validate a previously inspected archive as a holdout.

## Verification and integration

Run `cd backend && pytest -q tests/test_frozen_four_week_shock.py`, then the repository's complete backend, frontend, PostgreSQL, Docker and cloud CI. The regression data are **synthetic**; they test arithmetic, missing-week retention, ambiguous outcomes, cost identities, population withholding, source integrity and no-lookahead clocks.

This helper is offline and read-only. It makes no API, database, deployment, or broker changes. Integrate only after independent archive provenance and chronology review, protected holdout protocols, and realistic broker-specific cost evidence. Never use it to justify autonomous real-money execution.
