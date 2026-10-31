# Precommitted M1 exploratory research bundle (offline only)

This read-only research integration combines **five existing exploratory audits** behind a single caller-supplied, independently retained pre-outcome archive-cohort SHA-256. It is deliberately **not** a strategy approval, live signal, protected holdout, verified trading-cost model or broker order gate.

## Usage

~~~python
from app.offline_m1_precommitted_research_bundle import audit_m1_precommitted_research_bundle

# This digest must have been independently recorded BEFORE outcomes were inspected.
# Do not derive the expected digest from the reports under evaluation.
result = audit_m1_precommitted_research_bundle(original_v1_reports, externally_recorded_digest)
assert result["trade_authorized"] is False
~~~

The bundle first calls the existing require_m1_precommitted_cohort validator, which rejects missing, added, substituted or duplicated original-v1 archives against the registered identity set. It then evaluates archive robustness, whole-archive deletion stress (1–3 deletions), paired original/mirror/hindsight direction and receipt-rounding-aware break-even cost frontiers. It requires exact source-group and archive-count coverage, exact evaluated outcome counts, consistent source hashes and research lineage, fixed 0/5/10/20 bps scenarios, non-executing safety flags, and cross-auditor numerical agreement within the six-decimal original receipt precision.

An archive with no evaluated outcomes quarantines the **entire source-local group**, without imputing returns or allowing any of the five auditors to leak partial-cohort performance. A different complete source remains independently descriptive. The final report has a deterministic SHA-256 over the registered digest, upstream research hashes and conservative source-local summaries. The hash is only a tamper-evident self-declaration; it cannot establish independent custody or a registration timestamp.

## Evidence limits and release gates

- The original 32-archive exploration was negative after an illustrative 5 bps cost in every archive. This bundle does **not** rerun those archives or change that evidence. Synthetic tests do not establish historical performance.
- The archive identities are sorted by hash, **not by time**. No temporal source continuity, independent sampling, multiple-testing correction, genuine protected holdout or statistical significance is established.
- The mirrored signal and per-archive hindsight direction are diagnostics, not tradable predictions. No live feed, source-verified UTC, executable BID/ASK, commission, financing, slippage or actual broker fill has been verified.
- A valid digest supplied by a caller does not prove it was registered before the outcomes. The external registration record, licensed data provenance and independently verified chronology remain prerequisites for any credible protected evaluation.
- No network, provider, database, production route, alert, paper order, real-money order, paid service or secret is accessed. Outputs always declare trade_authorized=False, verified_profitability=False and independent_precommitment_verified=False.
- Keep draft/unmerged/undeployed pending exact-head backend, frontend, PostgreSQL, Docker and cloud CI plus independent production backup restore, rollback, authenticated health and hosting-ownership verification.

Run the synthetic regression suite:

~~~sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_precommitted_research_bundle.py
~~~
