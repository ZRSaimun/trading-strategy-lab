# Declared adverse-cost scenarios (offline only)

`backend/app/declared_holdout_cost_scenarios.py` runs the complete declared holdout release and exact-decimal cost attribution audit **before** exposing any scenario net amounts. It accepts 1–8 strictly validated, uniquely named, caller-declared adverse cash-debit scenarios.

Each scenario contains additional **nonnegative cash per observation** for spread, slippage, commission, financing and FX. Its extra cost is the exact sum of those amounts multiplied by the validated holdout observation count; stressed net cash is baseline net cash minus extra cost. This is not a percentage-of-price model, a bid/ask replay, a margin/equity simulator or a broker-calibrated CFD financing calculation. It does not rewrite historical outcomes or change the base audit.

At 1–29 observations all scenario totals, baseline net, receipt digest and worst-scenario metrics are withheld. Ties use lexical scenario ID; results are scenario-order and outcome-order invariant. The report permanently denies independent source/holdout/broker authentication, profitable-edge verification and demo/real order permission.

Tests: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_declared_holdout_cost_scenarios.py`. Synthetic fixture values are invented and never imply market profitability.

**Research limitations:** The underlying anchor, receipts, source archive hashes, UTC conventions and financing are caller-declared. External source authentication, untouched one-time holdout protection, actual executable spread/slippage/commission/financing/FX evidence, margin and intraperiod equity drawdown remain unverified. Do not merge or deploy until full exact-head CI and independent production backup restoration, rollback rehearsal and authenticated health checks are verified. No brokerage API calls or order execution.
