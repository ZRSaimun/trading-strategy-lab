# Frozen-intent as-of macro-calendar proximity audit (offline)

This **research-only** Python utility reports whether scheduled economic events were declared within fixed **±15-minute and ±60-minute** windows of a frozen completed-M1 signal. It does not fetch Forex Factory, Investing.com, news, prices or any licensed calendar; the caller supplies event-version metadata. It does not execute, paper-fill, alter signals, filter trades, or grant trading permission.

## Inputs and chronology

Call `audit_asof_macro_proximity(manifest, expected_manifest_sha256, calendar, expected_calendar_sha256)`. The manifest must pass the existing strict `frozen-next-open-intent-v1` validator. The calendar uses protocol `frozen-scheduled-macro-calendar-v1`, a source object with exactly `provider`, `instrument`, `snapshot_id`, and events with exactly `event_id`, `scheduled_at`, `known_at`, `impact`. UTC timestamps are minute-aligned integer epoch seconds. Impact is one of `HIGH`, `MEDIUM`, `LOW`. The calendar instrument must match the manifest instrument. No event actuals, surprises, forecasts, revised values, outcome returns, or unrecognized fields are accepted.

`known_at` is the publication clock of **this exact schedule/impact version**, not the date the event first appeared in some other version. A version is counted as known at a signal only when `known_at <= signal_at`. A later-known version inside the window is counted separately as *later-known*, not silently treated as absent or as contemporaneously known. Window endpoints are inclusive. The supplied version may be retrospective or falsely backdated; **the code cannot verify its clock or prove completeness**. Missing events cannot be detected from a supplied calendar alone. An empty calendar is not a safety clearance.

The two SHA-256 digests are order-independent consistency commitments for the supplied inputs. Preserve externally timestamped commitments and original authorized source snapshots to establish stronger chronology. Self-reported hashes, known-at clocks and a snapshot ID do **not** authenticate data or prove preregistration. Any retrospective revisions need their own version records and independently verifiable publication times; do not reuse final revised event metadata as historical known information.

## Output and limits

For each fixed window the audit counts signals with known high-impact events, any known events, later-known versions, and no declared events; it also reports exact event-observation totals. All eligible intents remain in the denominator. Declared pre-signal exclusions are preserved, not changed. Up to 50 bounded per-intent samples are returned. A sorted event clock and Fenwick-tree sweep avoids a naive intent-by-calendar Cartesian product. Input is bounded to 100,000 event records and the existing frozen-intent manifest limit.

The report always marks `independent_calendar_completeness_verified=false`, `independent_publication_clocks_verified=false`, `safe_to_trade=false`, `may_exclude_signals=false`, `may_execute_order=false`, and `verified_profitability=false`. This is a descriptive potential volatility/confounder diagnostic, **not** a post-hoc event blackout optimization, execution safety gate, or proof of profitable CRT/ICT signals.

## Verification and next steps

Synthetic tests cover publication boundaries, events announced after signals, concurrent events, impact tiers, inclusion boundaries, exclusions, order independence, tampered digests, unknown fields, source mismatches and bounded outputs. No real market archives, calendar vendor feed, broker bid/ask, commissions, slippage, financing, or untouched chronological holdout are evaluated here.

For historical studies, first authenticate calendar-version clocks and archive rights; preregister event hypotheses before untouched holdouts; retain all eligible signal outcomes, report event strata with source- and week-clustered uncertainty and realistic cost scenarios. Do not optimize window sizes on the evaluation sample. Production wiring requires separately verified rollback, backup and health readiness.
