# Declared holdout release gate (offline, development-only research)

`backend/app/declared_holdout_release_gate.py` adds an **offline, read-only** validation fence around a *single preselected candidate's* declared holdout evaluation. It does not call a broker, expose an API route, write a database, load an archive, or permit paper/real orders.

## Intended workflow

1. During development, freeze one candidate ID, its configuration SHA-256, the selection evidence SHA-256, exact source identity (provider, venue, account alias, instrument, quote side, UTC convention, settlement currency and archive digest), an embargo and non-overlapping validation/holdout clocks. A validation end precedes selection by the declared embargo.
2. Construct a chronological holdout **membership-only** census. Each observation declares an ID, source/row SHA-256, decision time and label-availability time. **No realized outcome or cost fields may appear** in the census or manifest. `prepare_declared_holdout_census_sha256` computes its deterministic digest. Freeze the census digest and expected population in the manifest.
3. Compute `prepare_declared_holdout_manifest_sha256(manifest)` and preserve it in an **independently trusted, immutable, timestamped external registry before the holdout starts**. The external registry should enforce a one-time evaluation claim and should record the immutable study and anchor IDs. This Python module does **not** provide or authenticate such a registry.
4. After the declared holdout ends and **all** labels and outcome receipts become available, call `audit_declared_holdout_release(manifest, census, anchor, outcomes, release_at_utc)`. The anchor's digest and timestamp must match the frozen manifest and predate holdout start. The complete outcome population must match the exact census. All timestamps are integer UTC Unix seconds.
5. Treat the result as a **declared-only** research diagnostic, not a strategy approval. Keep the actual holdout inaccessible to selection, repeated tuning, cost-model calibration and subsequent challenger evaluation.

The function rejects missing/extra/duplicate observations, repeated raw row digests, repeated decision times, wrong archive identities, mutated precommitted membership, outcome fields in preregistration inputs, late/altered anchor declarations, premature release, future/unobserved receipts, duplicate receipt hashes, floats, NaN, negative-zero strings and negative spread/slippage/commission/FX charges. All cash uses bounded exact-decimal strings. CFD financing is signed (a charge is positive, a credit negative); it is subtracted from gross P&L. Cost components are caller-supplied, not verified broker statements. One selected candidate is evaluated, with no holdout candidate ranking.

The result reports net declared cash, worst observation and observation-end drawdown. With fewer than 30 observations it reports `WITHHELD_INSUFFICIENT_HOLDOUT`, not a pass. Even with 30 or more, `DECLARED_EVALUATION_ONLY` **does not certify** statistical significance, profitable edge, market data provenance, spread/financing authenticity or independent holdout protection. Observation-end drawdown misses intraperiod losses, correlated trades and margin risk. A fixed positive holdout result cannot establish out-of-sample reliability without a properly registered research protocol and independent data.

## Critical security and scientific limitations

- The manifest digest and external anchor fields are **self-declared**. A caller can fabricate an earlier anchor time or recompute both digests. Only a separately trusted immutable registry with independent timestamp attestation and a one-time-release lock can prove precommitment and prevent multiple peeks.
- The module cannot authenticate raw archive bytes, market-data licensing, quote side, account records, settlement conversion, financing statements, true label-availability clocks or fill receipts. A digest-shaped string alone proves none of these.
- Historical BID-only candles are not executable bid/ask quotes. This is **not** an order simulator or an actual broker-cost backtest.
- Holdout observations may be selected or censored before the manifest is prepared; the gate cannot independently establish the eligible population. An external complete population registry is needed.
- Neither the module nor this PR opens holdout outcomes in any running product. Integration with PR #75, #142 and #144 should only occur after those branches are reconciled and a real trusted registry and source authentication exist.
- No real-money or demo orders may be sent by this module. Do not infer Trading 212 CFD API support.

## Local regression

```sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_declared_holdout_release_gate.py
```

Tests use only invented data, including a seeded 1,000-observation exact-decimal cost reconciliation. No actual historical returns, executable spreads or financing evidence are included. The 30-observation cutoff is an illustrative minimum gate, **not** a statistical power guarantee.
