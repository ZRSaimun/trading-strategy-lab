# Offline CFD financing rate decision-time audit (declared-only)

`backend/app/cfd_rate_decision_audit.py` provides `fingerprint_cfd_rate_decisions(scope)` and `audit_declared_cfd_rate_decisions(scope, rates, expected_scope_sha256)`. The module has no network, database, brokerage route, order submission or external data dependency.

## Why

A backtest can accidentally use a CFD overnight financing rate that was published or ingested *after* the decision being evaluated. This module selects the highest contiguous revision of each **explicitly declared rollover** available by its own decision timestamp. Later corrections cannot improve earlier research results. Any missing decision-time rate withholds the **entire** financing estimate, rather than silently treating missing evidence as a zero charge.

`scope` specifies one provider, venue, account alias, instrument, settlement currency, open/close/audit clocks and a strictly increasing bounded list of rollovers. Each rollover explicitly declares its ID, decision and rollover epoch-second timestamps, LONG/SHORT side, cash notional in the settlement currency, and 1–7-day multiplier. This **does not infer** whether a triple rollover, holiday, weekend or any multiplier is appropriate. `rates` is a bounded list of revisions with the same exact source identity, receipt ID, declared publication and ingestion clocks, two signed basis-point-per-day rates, and a statement SHA-256. Values are exact decimal strings; floating-point input is rejected.

The output is an **unrounded hypothetical signed estimate** of `notional_cash × selected_signed_bps_per_day × declared_day_multiplier / 10000`. Positive amounts mean declared charges, negative amounts mean declared credits. Broker-specific compounding, rate definitions, actual position notional, financing cutoff, day-count rules, cash rounding and currency conversion are **not** modeled. Never add the result directly to a realized P&L claim without independently authenticated broker statements and broker-specific reconciliation.

The expected scope SHA-256 catches accidental changes relative to a caller-provided digest, but does not prove pre-outcome preregistration or source authenticity. The statement hashes are caller-declared; even a perfect matching checksum is not a broker signature. Missing calendar days cannot be detected unless the independent expected rollover population is provided. Synthetic multi-year tests are **not** a multi-year market backtest.

## Next integration gates

1. Obtain permissioned, read-only native statements and verified rate/publication metadata from a supported broker. Independently establish account, instrument, statement population, rollover calendar and source custody; do not assume Trading 212 CFDs support its Invest/ISA API.
2. Independently freeze strategy configuration, cost assumptions, source manifest, walk-forward splits and untouched holdout before outcome observation; record a separately retained signed/timestamped anchor.
3. Reconcile each broker cash debit/credit, spread, commission, slippage, financing multiplier, currency conversion and rounding. If unavailable, report **unknown**, not zero.
4. Evaluate costs and drawdowns on protected, source-isolated out-of-sample folds with conservative stress, and report sample size, uncertainty, data exclusions and failures. A positive synthetic estimate is not evidence of profitable trading.

This is offline research only. `may_execute_order`, `verified_profitability`, `source_authenticated`, `realized_financing_verified` and `broker_rounding_verified` are always false. No demo or live order is authorized.
