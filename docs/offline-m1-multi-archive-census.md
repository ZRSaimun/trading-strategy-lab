# Multi-archive exploratory M1 confluence cost census — 29 October 2026

## Offline-only aggregator

app.offline_m1_multi_archive_census.audit_m1_multi_archive_census(reports) takes 2–64 **original v1** audit_m1_cost_sensitivity reports, validates their self-consistent research SHA-256, frozen 20-sweep / MSS3 / wick-FVG2 / five-bar confirmation / next-open / 15-candle-exit policy, full 70/30 exploratory split population and six-decimal weighted-mean reconciliation, nonempty win-fraction bounds, strict empty/unknown split handling, source identity, unverified epistemic flags, and the 0/5/10/20 bps illustrative cost grid. It rejects repeated original archive SHA-256 or repeated candle-manifest SHA-256. It groups by instrument **and** provider, calculates trade-count-weighted means from **six-decimal rounded** source receipts, and emits deterministic order-independent source-bound hashes. Empty outcomes remain unknown. It does not load ZIPs or prices, trade, connect to a broker, authenticate vendors, or grant permission. Self-hashing cannot prove source authenticity.

Synthetic regressions: 23 pytest cases for weighted costs, ordering, source isolation, duplicate identity, tampering, cost reconciliation, population reconciliation, empty cohorts and epistemic gates. To run:

~~~sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_multi_archive_census.py
~~~

The **32-archive historical replay below was independently computed from private owner-provided original ZIPs using an equivalent frozen rule implementation**, not by passing 32 original v1 JSON receipts through the new aggregator. Three prior baseline annual archives were reproduced exactly to six decimals (NSXUSD 2025, WTIUSD 2022, XAUUSD 2025). Full original archive bytes and individual candle/trade prices were **not** committed. The new aggregator's synthetic tests do not constitute a real-data end-to-end integration test.

## Frozen exploratory 32-archive replay

Original Library archives were processed independently, each with 20 contiguous M1 sweep/reclaim, within-five-completed-bar MSS3 + wick FVG, hypothetical next contiguous open entry, fixed 15-candle-close exit, gap censoring and first-in-time non-overlap. 0/5/10/20 bps are **flat illustrative round-trip deductions**, not verified executable spreads, slippage, commissions or financing. Original source-wall timestamps were **not** converted to verified UTC. No parameter search was performed in this replay.

| Instrument / provider label | Original ZIPs | Observed bars | Nonoverlap outcomes | Trade-weighted mean gross (bps) | Net 5 bps | Net 10 bps | Net 20 bps |
|---|---:|---:|---:|---:|---:|---:|---:|
| NSXUSD / HistData | 20 | 3,639,945 | 36,139 | +0.067812 | -4.932188 | -9.932188 | -19.932188 |
| WTIUSD / HistData | 7 | 742,805 | 6,445 | -0.288498 | -5.288498 | -10.288498 | -20.288498 |
| XAUUSD / HistData | 5 | 1,389,411 | 16,101 | -0.173695 | -5.173695 | -10.173695 | -20.173695 |
| **Total, not a cross-market trading portfolio** | **32** | **5,772,161** | **58,685** | **-0.037580** | **-5.037580** | **-10.037580** | **-20.037580** |

All **32** individual archives had negative mean return after the hypothetical 5 bps cost. The total line is descriptive weighting by signal count, **not** a risk-weighted, funded, or executable portfolio. The zero-cost positive NSXUSD gross mean (+0.067812 bps) is tiny and is not a demonstrated edge.

| Original archive (ASCII M1 ZIP) | Bars | Evaluated | Gross mean bps | Net 5 bps | Original ZIP SHA-256 prefix |
|---|---:|---:|---:|---:|---|
| NSXUSD 2016 | 341,629 | 2,349 | -0.570 | -5.570 | c78457c386eb |
| NSXUSD 2017 | 330,380 | 1,947 | -0.055 | -5.055 | 162b6e8b54b1 |
| NSXUSD 2018 | 348,607 | 3,336 | +0.489 | -4.511 | 0cab833575b5 |
| NSXUSD 2019 | 341,395 | 3,619 | -0.049 | -5.049 | f7e0ac7ce964 |
| NSXUSD 2020 | 340,022 | 3,637 | +0.459 | -4.541 | 896ff362259e |
| NSXUSD 2021 | 343,006 | 3,713 | +0.029 | -4.971 | ea22aa9f9a10 |
| NSXUSD 2022 | 342,771 | 3,872 | -0.306 | -5.306 | b6bfac92a74c |
| NSXUSD 2023 | 299,349 | 3,238 | +0.259 | -4.741 | 0282f3b419c2 |
| NSXUSD 2024 | 340,986 | 3,797 | -0.106 | -5.106 | 70429c487544 |
| NSXUSD 2025 | 340,553 | 3,783 | +0.137 | -4.863 | 865006539b7a |
| NSXUSD Jan 2026 | 27,837 | 297 | -0.364 | -5.364 | 62d23149b48d |
| NSXUSD Feb 2026 | 26,500 | 294 | +0.765 | -4.235 | 7904a738862d |
| NSXUSD Mar 2026 | 29,498 | 287 | +1.102 | -3.898 | d62628b53b06 |
| NSXUSD Apr 2026 | 28,019 | 297 | +0.403 | -4.597 | 3f16217c1714 |
| NSXUSD May 2026 | 27,750 | 302 | +0.262 | -4.738 | 5fc38b0cc763 |
| NSXUSD Jun 2026 | 29,189 | 289 | +0.593 | -4.407 | 5a97ec616b67 |
| NSXUSD Jul 2026 | 30,396 | 329 | -0.352 | -5.352 | dd8a7ccb5651 |
| NSXUSD Aug 2026 | 28,432 | 291 | +0.756 | -4.244 | b8d8cf3f1599 |
| NSXUSD Sep 2026 | 27,957 | 292 | -0.367 | -5.367 | 2aa6fbf0a761 |
| NSXUSD Oct 2026 (partial) | 15,669 | 170 | +0.522 | -4.478 | 811d9a72f8bc |
| WTIUSD 2022 | 354,224 | 3,450 | -0.286 | -5.286 | 876d8e31b133 |
| WTIUSD 2023 | 280,046 | 1,945 | -0.100 | -5.100 | 0e76bb3ed8c7 |
| WTIUSD Jun 2026 (sparse) | 3,106 | 24 | -2.486 | -7.486 | c600c87bb175 |
| WTIUSD Jul 2026 | 31,046 | 309 | +1.373 | -3.627 | 5889855eca2a |
| WTIUSD Aug 2026 | 29,278 | 290 | -1.358 | -6.358 | 21252870432f |
| WTIUSD Sep 2026 | 28,922 | 287 | -0.933 | -5.933 | ae988d595f9b |
| WTIUSD Oct 2026 (partial) | 16,183 | 140 | -2.724 | -7.724 | 5c8e707f05ce |
| XAUUSD 2022 | 354,628 | 4,064 | -0.150 | -5.150 | e752b9d83a14 |
| XAUUSD 2023 | 308,812 | 3,461 | -0.198 | -5.198 | 89a4f3f7ec2a |
| XAUUSD 2024 | 355,652 | 4,387 | -0.036 | -5.036 | 6d47f5cb269e |
| XAUUSD 2025 | 354,011 | 4,008 | -0.388 | -5.388 | dd0b4dc6983c |
| XAUUSD Oct 2026 (partial) | 16,308 | 181 | +1.156 | -3.844 | 59d0ba305f16 |

The prefixes above are **not full provenance proofs**. Each original archive was locally SHA-256 hashed; full original SHA-256 values remain in private local replay summaries. Previously documented baseline full hashes are in offline-m1-cost-sensitivity.md.

## Critical limitations and handoff

- NSXUSD 2016/2017 had thousands of timestamp discontinuities; WTIUSD 2023 also had substantial gaps, and WTIUSD June 2026 was sparse. Contiguous segments reset rather than fabricating missing candles. Verify source conventions, DST, completeness, market calendars, original provider provenance, and rights before relying on any figures.
- The years/months were chosen from **available owner uploads**, not from a preregistered universe. WTIUSD 2024–2025 and most XAUUSD 2026 months were not present as matching ASCII archives. No protected untouched chronological holdout was maintained. These years are now *exploratory-exposed*, not a new holdout.
- These outcomes use **unverified single-side candle proxies**, not broker BID/ASK, executable fills, financing, actual costs, market impact, latency, or account leverage. A flat 5 bps cost is illustrative; its actual suitability differs by instrument and venue.
- A simple negative average at a flat cost does not prove every conceivable CRT/ICT implementation loses; it challenges profitability for **this specific fixed proxy under this assumed cost scenario** on the evaluated uploads.
- Loop 1: authenticate original archives, source-wall clock and data rights. Loop 3: independently check chronological cohort leakage, executable-side costs, financing and untouched new-data holdouts. Loop 5: never promote these exploratory results to a live signal. No production deploy, broker submission or autonomous order permission is authorized by this research.

## 29 October 2026 — v1 receipt partition integrity hardening

The aggregator now independently validates **development**, **later exploratory (not holdout)** and **all exploratory** summaries. It enforces the original deterministic 70/30 split by evaluated-outcome count; each split must have the exact cost-grid keys and internally reconciled six-decimal mean returns, with valid gross-win fraction (0–1). A zero-count split must have null performance and cannot be made profitable by a self-rehashed declaration. The overall gross mean must reconcile to the count-weighted split means within 0.000002 bps of independent rounding, and evaluated outcomes cannot exceed the original bar count. These checks defend against inconsistent self-declared reports, **not** fabricated but internally consistent source data. The historical 32-archive exploratory replay was **not rerun** by this change. No protected holdout, verified execution costs, source authentication or trading authority is established.


## 29 October 2026 — diagnostic scan and gross-win split reconciliation

Additional fail-closed checks validate the *self-declared* original-v1 source-wall scan counters after checking the receipt hash. Discontinuities cannot exceed `bar_count - 1`; backward jumps and adjacent duplicates cannot jointly exceed discontinuities; sweep counts cannot exceed the bar population; confirmations cannot exceed sweeps; and ambiguous scan events cannot exceed twice the bar population (a bar can carry both a confirmation ambiguity and a two-sided sweep ambiguity). All diagnostic counters must be nonnegative plain integers, not booleans, strings or floats.

The all-exploratory gross-win fraction must also equal the outcome-count-weighted development and later-exploratory gross-win fractions within **0.000002**, allowing independent six-decimal rounding. The same rule never treats the later partition as a protected holdout. These validations catch internally inconsistent re-hashed declarations; they do **not** establish original candle authenticity, trade-level win counts, independent observations, execution costs, statistical significance, or any profitable edge. Synthetic tests cover invalid counter types, impossible scan populations, contradictory fractions and rounding boundaries. No archive bytes or prices are published, and the 32-archive replay was not repeated for this validation-only change.
