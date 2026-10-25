# Causal M1 detector-to-intent lineage audit (offline, read-only)

`backend/app/causal_m1_lineage_audit.py` adds an **isolated population continuity control** for the already merged M1 sweep/MSS-proxy/FVG detector and fixed ATR14 bracket compiler. It does not change their thresholds, produce an order, query a broker, mutate data, select profitable trades, or report returns.

## Usage

Call `audit_causal_m1_lineage(source, bars, observed_through_close_at, expected_snapshot_sha256, expected_manifest_sha256, expected_pre_signal_evidence_sha256, sample_limit=20)`. For zero confirmed candidates, supply **only** the snapshot hash; both ATR hashes must be absent. Hashes must be lowercase 64-character SHA-256 strings. Obtain the three expected digests from an **independently timestamped, pre-outcome** record where possible; supplying hashes calculated in the same retrospective evaluation does **not** establish preregistration.

The auditor recomputes `detect_completed_m1_confluence` over the **entire supplied snapshot** (not a handpicked candidate list), verifies the supplied snapshot digest, then recomputes `compile_causal_atr_intents` over **all** confirmations. Every detected `(path_id, signal_at)` must occur **exactly once** as an eligible intent or a declared pre-signal exclusion, with the original direction preserved. Both compiler hashes must match the separately supplied expected digests. Missing/dropped confirmations, altered source/candles, malformed hashes, altered directions, invalid OHLC, future bars, and wrong cutoff fail closed.

A zero-confirmation scan is `NO_CANDIDATES_NOT_A_BACKTEST`; a valid nonempty reconstruction is `COMPLETE_RECONSTRUCTION_NOT_VALIDATED_EDGE`. Any declared exclusions yield `PRE_SIGNAL_EXCLUSIONS_NO_POPULATION_RETURN`. Sweep, pending, expired, gap-censored and ambiguous counts remain visible. Bounded candidate samples (0–50) never determine total counts.

## Boundaries and limitations

This is **continuity against a caller-supplied snapshot**, not proof the snapshot covers the entire licensed vendor archive. A digest alone cannot prove the archive's provenance, source rights, UTC convention, the time of registration, or untouched holdouts. Earlier confirmations reconstructed from later bars are historical simulations, not independently recorded live signals. The ATR stops/targets remain hypothetical, the data may be BID-only, and the report does not validate spread, slippage, commission, financing, latency, executable fills, exposure, or profits. Do not treat synthetic regression tests as a backtest. Do not silently remove excluded candidates or use the audit as a permission to trade.

For any future research claim, first verify source licensing and immutable source/timebase, preserve externally timestamped snapshot/manifest/evidence hashes before inspecting outcomes, retain every candidate and exclusion, use purged chronological holdouts, and report conservative execution-cost scenarios and uncertainty with overlapping exposures. The tool always sets `verified_profitability=false` and `may_execute_order=false`.

## Verification

Run `cd backend && PYTHONPATH=. python -m pytest -q tests/test_causal_m1_lineage_audit.py`, then the full backend, frontend, PostgreSQL, Docker and free-cloud CI checks before merge. Tests use only synthetic M1 fixtures and exercise normal/short, zero-signal, missing/gapped candles, tampering, candidate omission, direction mismatch, bounded samples, prefix invariance, source and digest integrity.
