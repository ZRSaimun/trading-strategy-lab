# Declared M1 session gap runs — offline only

`app.declared_m1_gap_runs.audit_declared_m1_gap_runs` is an opt-in, read-only diagnostic for the **absence of declared expected UTC completed one-minute bars**. It takes an existing compiled `ExpectedM1Manifest` and an explicit list of observed UTC bar-start timestamps. It makes no provider requests, imports, corrections, calendar downloads, subscriptions, database writes, or trading decisions.

It first re-compiles the manifest and refuses altered fields or fingerprints. Timestamps must be exact integer UTC minute starts, completed by the declared observation clock; observations are capped at 20,000 rows. It counts duplicate observed rows and unique unexpected observations separately from missing expected minutes. It then groups consecutive missing minutes **only inside each declared session**, splitting runs at operator-declared exclusions, present minutes and session boundaries. Even adjacent separately declared sessions do not merge. The histogram, longest run, count and bounded first samples reconcile to the exact missing expected population. Missing observations are not automatically filled, and unexpected observations are not silently dropped from the report.

The status `DECLARED_COVERAGE_COMPLETE_UNVERIFIED` means only that the supplied timestamps cover the supplied manifest with no duplicate/unexpected timestamps. It is **not** a verified exchange session, authenticated market feed, licensed source, or proof of executable BID/ASK or market freshness. All reports set `expected_calendar_verified=false`, `source_authenticated=false`, `data_rights_verified=false`, `live=false`, `may_execute_order=false`. Source-wall HistData clocks cannot be treated as UTC without independent timezone/DST evidence. A closure or holiday must be independently established; missing bars must never be reclassified as closures merely to improve coverage.

Run the synthetic tests without any market-data credentials:

```sh
cd backend && PYTHONPATH=. pytest -q tests/test_declared_m1_gap_runs.py
```

Before any operational use, verify provider instrument entitlement, licensing and independently versioned calendar/session/DST provenance; obtain authenticated prospective completed-bar receipts and trusted backend UTC custody. The large Loop 1 draft PR still requires exact-head CI, independent staging, backup restoration, rollback rehearsal and authenticated production health checks before merge or deployment.
