# Offline point-in-time CFD FX conversion audit

`backend/app/declared_fx_conversion_audit.py` extends the **declared-only** partial-fill and as-of-financing audit with an explicit close-time FX quote population. It does **not** connect to any broker, fetch market data, submit demo/real orders, authenticate receipts, book currency conversions, or prove profitability.

## Inputs and accounting

Call `fingerprint_fx_conversion_policy(manifest, policy, financing_sha, specs_sha)` to declare a reporting currency, FX quote provider/venue and quote freshness maximum (0–3600 seconds). The reporting currency must differ from the financing manifest's settlement currency. The fingerprint also binds upstream manifest/spec digests, account identity and **every declared position closing timestamp**. It is an integrity fingerprint, **not** an independent signed preregistration.

Call `audit_declared_roundtrip_fx(manifest, financing_versions, financing_sha, specs, specs_sha, fills, cutoff=..., fx_policy=..., expected_fx_policy_sha256=..., fx_quotes=...)`. The module reruns `audit_declared_roundtrip_net` itself rather than trusting caller-provided net P&L. One bounded, exactly schema-validated FX quote is required for **each** declared closed position. A quote includes position/account IDs, FX source, settlement/reporting currency, quote ID, UTC observed/received seconds, positive exact-string bid/ask and declared SHA-256 statement identity. The pair is **reporting currency per unit of settlement currency**, e.g. a GBP settlement converted to USD uses USD per GBP. Inverted pairs are rejected.

The quote must have been observed **and received by the position close**, with observed age within the frozen policy, even if the research evaluation cutoff is later. A quote first received after the close cannot be backfilled into that historical close. Later financing revisions may change the as-of settlement net without retroactively changing the declared FX quote. No FX rate interpolation or fallback is performed.

For each position, the module calculates with exact `Decimal` (no rounding):

```text
mid_reporting = settlement_net * (fx_bid + fx_ask) / 2
net_reporting = settlement_net * (fx_bid if settlement_net >= 0 else fx_ask)
fx_half_spread_cost = mid_reporting - net_reporting  # nonnegative
```

This is a conservative **hypothetical** translation: positive cash is sold at bid, liabilities are bought at ask. It does not mean the broker charged or executed that FX spread, and is not a validated accounting treatment for any broker. Aggregates are withheld when any declared financing or FX quote is missing. Output includes sorted per-position results, deterministic quote declaration digest, full aggregate and explicit `False` authenticity, execution and profitability flags.

## Validation and limits

The audit rejects missing/extra/duplicate positions, mismatched account or FX provider, reversed currencies, crossed or nonpositive FX quotes, conflicting reused quote IDs, late receipt, stale quote, invalid/future clocks, invalid SHA, malformed exact decimal, invalid or mutated policy fingerprint, and unsupported extra fields. It has no network or filesystem side effects. Synthetic tests cover positive and negative position cash, revision availability, deterministic ordering and fail-closed populations. Run `cd backend && pytest -q tests/test_declared_fx_conversion_audit.py`.

**Limitations:** The upstream financing manifest currently declares one settlement currency across positions; this is not a cross-currency broker cash ledger. All rates, timestamps, source identities, receipt hashes, contract multipliers, fills and financing schedules are caller-provided and unverified. No bank settlement rounding, holiday calendars, real executable FX liquidity, multi-year authenticated source coverage, independent holdout seal or trading edge is established. Keep live and paper order interfaces disabled; production deployment requires independent rollback, backup restoration and post-deploy health verification.
