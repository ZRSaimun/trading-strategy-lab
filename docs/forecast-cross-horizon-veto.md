# Loop 5 — offline cross-horizon forecast veto

**Scope:** `frontend/lib/forecast-cross-horizon-veto.ts` is a pure read-only diagnostic over the existing `assessOfflineForecastAgreement` output. It does not replace the within-horizon two-model agreement gate.

## Decision policy

Require valid, ordered, same-source 1-, 3- and 12-completed-candle horizon assessments. If any horizon has missing, uncertain, or conflicting within-horizon evidence, abstain. If all horizons individually agree but directions differ between horizons, abstain with `CROSS_HORIZON_CONFLICT`. If the assessment is stale relative to the **caller-supplied** as-of time, abstain. All three must agree to yield `RESEARCH_CONSENSUS_ONLY`, which **never** permits alert delivery or paper/live order submission.

Cross-horizon direction disagreement is **not** mathematically invalid: a 1-candle UP forecast can coexist with a 12-candle DOWN forecast. This is a deliberately conservative research review veto, not a claim that one model is wrong. Cross-horizon agreement does not prove calibration, profitability or independent evidence. Probabilities are not aggregated across horizons, and no calibrated confidence or executable quote is produced.

## Evidence and limits

All outputs explicitly carry `UNVERIFIED_LOCAL_RESEARCH`, `live=false`, `authenticated=false`, `persisted=false`, `alertsEnabled=false`, `execution=NONE`, and `ordersSubmitted=0`. A source label and caller clock are not authentication. Historical BID OHLC bars are not executable broker bid/ask quotes. This gate must not be presented as a functioning notification, forward demo, or live trading system.

## Tests

`cd frontend && npm test` includes 13 synthetic cases for aligned UP/DOWN, cross-horizon veto, insufficient/uncertain/conflicting models, staleness boundary, invalid timestamps, malformed horizon identity, probability consistency, non-execution and deterministic replay. `npm run typecheck` and the full GitHub CI pipeline are required before merge.

## Loop 1 handoff

Provide authorized source-authenticated completed candles, server-owned receipt timestamps, persistent append-only issuance/settlement records, session-aware gap treatment, transactional alert outbox with multiworker recovery and independent transport receipts. Reassess this veto using **prospectively** captured forecasts; keep paper fills isolated from historical BID prices. Any real order still requires eligible documented broker API/account, current executable quote, owner-confirmed order and enforced risk limits. No deployment or live alert activation is authorized by this research gate.
