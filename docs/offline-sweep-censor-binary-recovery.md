# Offline censored-exit binary recovery sensitivity (Loop 2)

Run from `backend` on an **existing local v3 report**:

```bash
PYTHONPATH=. python -m app.offline_sweep_censor_binary_recovery /path/to/report.json
PYTHONPATH=. pytest -q tests/test_offline_sweep_censor_binary_recovery.py
```

The read-only auditor invokes the existing `offline_sweep_censor_threshold.audit_research` validation before doing arithmetic. It accepts only the frozen v3 cohort population and validated illustrative **additional** 0/5/10/20-bps scenarios. The original source archives are not opened. It never changes admissions, entries, stops, exits, risk gates, order permissions or data. Duplicate JSON keys and files above the existing 20 MB limit are rejected.

For each cohort and cost scenario, assume *only for a counterfactual* that each entered-but-censored exit would have gross return either **+2R** or **−1R**. All known observed net-R returns and the implied additional censored cost remain fixed. If there are `N` censored positions, the hypothetical full-entered net-R sum with `k` censored wins is:

```text
observed_net_R - censored_additional_cost_R - N + 3*k
```

The report returns the minimum **integer** `k` in `[0,N]` that makes this hypothetical total nonnegative, or `null` when no such integer exists. If `N=0`, it reports `NO_CENSORED_EXITS` and a null fraction rather than fabricating a censored win rate. The all-loss and all-win hypothetical sums are provided for independent arithmetic review. A nonnegative sum is **not** evidence of positive expectancy or statistical significance.

**Critical limitations:** +2R/−1R are arbitrary declared assumptions, not upper/lower bounds on missing exits, actual returns, broker fills or forecast probabilities. The original stop-first source-OHLC proxy can exceed −1R after adverse opens, and censored outcomes are genuinely unknown. Results cannot be treated as actual portfolio outcomes or a replay: different realized exits might alter later capacity-admitted trades. The original archives, provenance, source-local timezone, executable BID/ASK costs, financing and independent forward holdout remain unverified. Previously inspected later slices are exploratory. No broker order authorization, deployment or profitable-edge claim is implied.
