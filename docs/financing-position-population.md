# CFD financing closed-position population reconciliation (offline only)

The isolated module at backend/app/financing_position_population.py is a stdlib-only **research gate** over the merged financing_vintage_audit.py. It neither calls a broker nor enables orders. Its purpose is to avoid a plausible but false *portfolio* financing total when a backtest quietly omits an expected position, an expected rollover receipt, or a later-corrected charge.

## Contract

Call fingerprint_financing_position_population(manifest) to compute a deterministic digest of a **caller-declared** population, then independently preserve the digest before any evaluation if preregistration is desired. Call audit_financing_position_population(manifest, versions, expected_manifest_sha256) with that digest and a flat receipt-version list. The exact-key manifest is:

- protocol: declared-financing-position-population-v1.
- source: provider, venue, account_alias, settlement_currency (one currency only).
- positions: a bounded, nonempty list of position_id, instrument, opened_at, closed_at, audit_asof, sorted required_rollovers. Each position is required even if it has no financing receipts.
- cutoffs: strictly increasing UTC epoch seconds, each **at or after all positions close** and **no later than any position's audit-as-of**. Use separate batches to compare earlier portfolio vintages.

Versions use the exact revision-row schema of the underlying single-position financing audit, including position/source/currency identity, unique receipt ID, rollover timestamp, publication and ingestion times, statement SHA-256, and signed two-decimal amount. Positive amounts are debits, negative amounts credits. Reused receipt IDs across different positions fail closed. Instrument identities may differ, but the account, provider, venue and settlement currency must agree. No FX conversion is attempted.

For each cutoff, the underlying audit chooses only revisions published **and** ingested by then. The aggregate is calculated in exact decimal cents **only when every declared position has all due receipts**. An absent receipt, no declared due rollover schedule, malformed source or duplicate identity cannot silently become zero financing. Results distinguish COMPLETE_SELF_DECLARED_ONLY from WITHHELD_INCOMPLETE_DECLARED_FINANCING; missing or unverified positions and selected revisions are explicit. The declaration digest covers all supplied revisions and changes on later correction. The membership digest excludes receipt revisions by design, so later broker corrections do not retroactively change declared position membership.

## Limitations and release gate

The expected population and rollover schedule are **self-declared**. Matching SHA-256 hashes do not prove that every actual position, calendar rollover or trial was included, that registration preceded outcomes, that a statement is authentic, or that archive use is licensed. A portfolio may have legitimate zero-financing positions, but the gate intentionally withholds aggregate totals for an empty declared schedule rather than infer free financing. The module does not handle mixed-currency portfolios, FX conversion, weekend/triple swaps, changing contract sizes, actual executable spreads, slippage, commissions, net P&L or risk-adjusted return. All source-authentication, execution and profitability flags remain false.

Synthetic-only test command: cd backend && PYTHONPATH=. pytest -q tests/test_financing_position_population.py. No production route, database migration, archive publication, credentials, order path, API call or spending is involved.
