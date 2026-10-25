# Offline HistData archive-audit triage (Loop 1)

The new `histdata_audit_triage` command consumes an **untrusted JSON report** from a separate offline ZIP scanner. It does not open, authenticate, repair, deduplicate, import or replace original ZIPs or candles. It never contacts a provider, broker or production database.

From the `backend` directory, with the audit report held in a private directory:

    PYTHONPATH=. python -m app.histdata_audit_triage /private/histdata-audit.json
    PYTHONPATH=. python -m pytest -q tests/test_histdata_audit_triage.py

The CLI reads a bounded regular file without following a final-path symlink. It rejects ambiguous JSON keys, NaN/Infinity, duplicate archive identities, inconsistent row arithmetic, impossible source-clock/declared-offset mappings, and summary totals that do not reconcile to individual records. It never trusts an externally supplied `FORMAT_OK_NO_COLLISIONS` status if counters contradict it.

The triage also reconciles the scanner's **observed-minute** arithmetic: UTC endpoints must be minute-aligned; unique timestamps cannot exceed the inclusive endpoint span; the reported unobserved-minute count must equal that span minus unique timestamps; and gap-event/largest-gap counters must be mutually possible. For `E > 0` reported gap events containing `M` unobserved minutes, the largest separation in minutes must be at least `ceil(M/E) + 1` and at most `M - E + 2`; zero events require zero missing minutes and zero largest gap. These are **necessary arithmetic constraints only**: a fabricated or internally inconsistent distribution can still escape detection without the original timestamps. These checks detect contradictory metadata, **not** missing trading sessions. The 27 previously audited archive summaries satisfy these equations, but the original ZIPs remain unverified and no data is approved for import.

The output reports archive filenames, counts and quarantine reasons without OHLC values or content hashes. A clean-looking file remains `FORMAT_ONLY_RIGHTS_UNVERIFIED`, **never research-ready**. Files with duplicated, conflicting, backward, invalid or out-of-period timestamps are `QUARANTINE_REVIEW`. All outputs prohibit auto-import, volume-dependent research and order execution.

This checks only the **internal consistency of the scanner report**. It does not independently verify ZIP bytes, CRC, provider signatures, fixed EST convention, DST handling, market sessions, volume classification, retention/display/non-display rights, executable bid/ask, delivery latency or historical price accuracy. A fabricated report can be internally consistent. Verify original ZIP SHA-256 separately against independently obtained authorised archives. Do not silently sort, repair, merge or backtest collision-affected minutes. Keep audit inputs private; never commit real archive hashes, prices or credentials.

No new API, migration, network call, subscription, broker execution or production activation. This complements the raw ZIP validator and draft PR #43 ASCII/MetaTrader parity diagnostic. CI uses synthetic fixtures. Before deployment verify latest-head CI, source rights, disposable staging, production backups, rollback and post-deployment health checks.
