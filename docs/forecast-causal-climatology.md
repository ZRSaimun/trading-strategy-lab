# Loop 5: causal climatology comparator (disconnected research)

The offline-only function audit_causal_climatology compares frozen issued
probabilities with a causal Jeffreys-smoothed empirical UP-rate baseline.
It accepts only a replay-validated ForecastEventStore.load snapshot and a
caller-declared evaluation cutoff. It performs no I/O.

For each exact model and horizon (1, 3, 12), a fixed nonoverlapping
training census is selected by base and target candle BEFORE outcome status
is inspected. A training label counts only if its declared settled receipt
strictly predates the forecast issuance. Unknown, pending, void, late and
overlapping labels never become invented outcomes. The baseline probability
is (prior_up + 0.5)/(prior_count + 1), the Jeffreys Beta(1/2,1/2)
posterior mean. Baseline and issued probabilities are scored on the SAME
settled rows using paired Brier and Bernoulli log-loss regret.

The evaluation census is now also fixed **before** inspecting any outcome:
for each model/horizon in issuance order, a matured forecast is admitted
only when its base candle starts strictly after the last admitted target
candle. This conservatively prevents shared base/target closes and
horizon-overlapping forecasts from inflating the minimum 30 scored
observations. Missing/void labels and training-insufficient members still
occupy their predetermined census slots. `maturedAtDeclaredCutoff`
counts all matured issued forecasts, `nonoverlappingMaturedCensus` counts
preselected disjoint members, and `overlappingMaturedExcluded` counts
excluded overlaps. The two latter counts sum to the matured count.

Default minimum: 30 observed prior nonoverlapping outcomes and 30 scored
evaluations **on the disjoint evaluation census** per model/horizon. Training and evaluation missingness above
10 percent withhold performance. Evaluation cutoff cannot precede any
issuance, and labels after it remain unavailable.

LIMITATIONS: No authenticated vendor receipt, trusted clock, protected
holdout, executable bid/ask, transaction costs, independent fills, measured
returns or statistical significance. Disjoint sampling reduces mechanical overlap but not serial dependence,
selection and regime shifts remain. Positive scores cannot authorize trades.
Every notification/paper/live permission is false, and financial returns
and maximum drawdown are null. No production route, feed, worker, broker,
payment, dataset write or alert is enabled.

Tests: cd backend && PYTHONPATH=. pytest -q tests/test_forecast_causal_climatology.py

Loop 1 handoff: independently authenticated entitled prospective completed
candles, trusted server UTC custody, provider/side/session lineage and
missing-issuance reconciliation. Keep draft/undeployed until exact-head CI,
restorable backup, rollback rehearsal and authenticated production health.
