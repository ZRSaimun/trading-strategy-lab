# Stressed-equity risk-preview hardening (26 October 2026)

The owner-authenticated, **non-executing** `/api/broker/stress-preview` and `/api/broker/order-gate-preview` diagnostics previously compared illustrative margin and leverage against **initial** declared equity. A proposed loss can make an initially compliant position exceed its limits.

The standalone stress preview now reports `stressed_equity_remaining_cash = account_equity - stressed_loss_if_filled` and `assumed_stressed_effective_leverage = proposed_notional / stressed_equity` when positive and finite. `assumed_effective_leverage` remains the **initial-equity** metric for compatibility. The `assumed_margin_covered_by_equity` and `within_user_leverage_cap` booleans now conservatively compare against stressed equity. Exhausted/nonfinite equity, nonfinite leverage, or a positive loss rounded away by floating-point precision **fails closed**; invalid leverage is serialized as `null`, never NaN or Infinity.

The combined order-gate diagnostic also deducts the proposed stressed loss and **other positions' incremental reserved downside** from current declared equity before comparing combined reserved margin, gross leverage and Invest/Stocks ISA cash-account gross funding. Already marked unrealized losses are not subtracted again because current equity is assumed to include them. The response includes `portfolio_exposure_scenario.remaining_stressed_equity_cash` and a `portfolio_stressed_equity_positive` check.

These assumptions do **not** establish available broker buying power, authenticated quotes, account positions, margin schedules, FX conversions or maximum possible losses. A real stop can fill beyond the hypothetical stress price, and a cash account can have less available funds than equity. All preview responses still return `may_execute_real_order=false` and `may_execute_paper_order=false`. No order sender, credentials, broker connection, persistence, migration, subscription or paid request was added.

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_stressed_equity_preview.py tests/test_broker_stress.py tests/test_portfolio_risk_gate.py tests/test_cash_account_gate.py tests/test_order_gate_api.py
```

This change is separate from open reservation PR #26, human-review PR #79 and sizing PR #82; it does not integrate their disconnected state or make them merge-ready. A passing preview cannot authorize execution. Before production deployment, independently verify the production workspace, restorable backup, rollback and post-deployment health checks.
