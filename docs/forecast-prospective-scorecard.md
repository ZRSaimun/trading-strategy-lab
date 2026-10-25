# Loop 5 — conservative forecast journal scorecard (disconnected)

`backend/app/forecast_prospective_scorecard.py` is an opt-in **read-only** summary of an already validated `ForecastEventStore.load(session_id)` result. It adds no route, scheduler, feed, broker, alert sender, table or migration. It does not modify database records. The journal source is explicitly **unauthenticated**, even if the input calls itself prospective.

Group by immutable model version and candle horizon (1, 3, 12), never mix providers or instruments (the underlying journal is source-isolated). Count **all issued forecasts** in the denominator: settled, pending and void-on-gap. With fewer than 30 settled outcomes in a group, withhold performance scores. At or above the minimum, report conditional-on-settlement Brier, log loss, equal-width-bin ECE, up frequency, directional accuracy for non-0.5 predictions and a descriptive Wilson interval. These are *forecast quality descriptors*, not validated statistical inference or trading profitability. A 0.5 prediction abstains from directional accuracy, but still contributes to Brier/calibration/log loss.

The function checks identity, event/outcome linkage, status and timing consistency and fails closed on malformed or conflicting records. It **does not independently authenticate** provider receipts or establish that data arrived live; callers must use `ForecastEventStore.load`, not arbitrary dictionaries. The journal's internal digest is not independently tamper-proof.

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_forecast_prospective_scorecard.py`.

**Interpretation caveats:** Overlapping 1/3/12-candle targets are dependent; void and pending outcomes can create selection bias; calibration binning and the Wilson interval are descriptive only. Scores may reflect a fabricated or unrepresentative data source. There are no genuine bid/ask execution quotes, spread/slippage/commission/financing adjustments, broker fill reconciliation, net returns or drawdown. No real-money order may be placed on these scores. Production remains unchanged.

## Loop 1 handoff

Provide entitled authenticated completed-candle observations with exact provider/venue/instrument/side, trusted server receipt times, session-aware closure/gap policy and independently verifiable source receipts. Validate durable journal replay, PostgreSQL process-kill recovery, and independently verifiable alert delivery before enabling operational prospective forecasting. To measure paper P&L, independently capture authenticated bid **and** ask plus fees, slippage, financing, positions and order/fill timestamps; do not use historical BID bars as executable prices. Require a tested restore, rollback and health checks before deployment.
