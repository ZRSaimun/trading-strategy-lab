# OANDA v20 practice transaction-window census — bounded and read-only

The offline module backend/app/oanda_practice_window_census.py audits already-validated caller-supplied summaries from backend/app/oanda_practice_transaction_range.py. The optional inspection wrapper uses only the existing explicitly enabled GET-only OANDA practice adapter. The adapter is network-disabled by default. There are no order methods, live hosts, secret storage, database writes, background polling, or trading permissions.

## Contract

- plan_practice_transaction_windows(first_id, last_id) partitions canonical positive IDs into adjacent, nonoverlapping ranges of up to 100 IDs. Maximum 20 windows / 2,000 declared IDs.
- audit_practice_transaction_windows requires exactly one validated summary for every expected window, in order. It rejects missing/reordered/duplicated windows, mismatched provider/account, inconsistent counters, duplicate/out-of-range IDs, event-type discrepancies, forged trust or execution claims, malformed hashes and any broker-reported latest-transaction cursor drift. It aggregates observed and missing IDs, with a maximum 20-ID gap sample.
- inspect_practice_transaction_windows accepts an existing practice adapter, a timezone-aware as_of cutoff, an explicitly pinned latest transaction ID and a max_requests budget (default 10, absolute maximum 20). It validates all inputs before the first GET and aborts additional GETs immediately if a response cursor differs from the pin.
- census_sha256 is a deterministic hash of canonicalized declared summaries. If a fingerprint was independently frozen before evaluation, expected_census_sha256 can detect subsequent changes. A hash alone is not a broker signature or proof of independently retained evidence.

## Interpretation and limitations

NO_GAPS_IN_DECLARED_RANGES means only that the supplied summaries show all IDs in the explicitly requested interval. It is not proof of complete account history or authentic broker transactions. Some providers may legitimately skip IDs. A stable cursor is not a broker attestation, nor proof of an atomic snapshot or absence of in-place corrections.

The reports omit per-event timestamps, so the offline census cannot verify cross-window event-time monotonicity or a shared as-of cutoff for independently supplied summaries. The optional wrapper passes one cutoff through the existing single-window validator, but multiple GETs are not a transactional snapshot. No original HTTP byte custody, independently verified account identity, actual fills, real bid/ask execution, commission, CFD financing, FX settlement, or net-of-cost profitability is established.

Before backtesting or execution-readiness use: obtain owner-authorized read-only practice-account evidence; independently preserve original broker statements and cursor lineage; reconcile source-native transactions with balances, cash, commission, financing and currency conversions; freeze the evaluation protocol and untouched holdouts; and measure realistic spread/slippage/liquidity stress. Never infer a Trading 212 CFD order API.

## Release gate

Keep PR #138 draft, unmerged and undeployed until exact-head full CI and independent production release safeguards are verified. The main Render Blueprint currently specifies autoDeployTrigger: checksPass. Confirm the owner-controlled Render workspace and auto-sync state, restorable backup, rollback and health checks before any merge. No real-money trades are authorized by this module.
