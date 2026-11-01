# Loop 4 — immutable one-order human review packet (offline only)

`backend/app/live_order_review.py` creates a **disconnected, read-only** risk-review packet with a SHA-256 digest bound to the complete owner-supplied order, account alias, client order ID, exact quote identity, bid/ask, source timestamps, server issue time, expiry and quote timing policy. It uses bounded plain-decimal strings and exact `Decimal` arithmetic. It rejects unknown fields, floating-point inputs, malformed monetary values and unsafe order directions.

Checks cover supported public API account category (Trading 212 Invest/Stocks ISA only; **no Trading 212 CFD API orders**), cash-account BUY-only new entries, protective stop direction, worse-than-stop stressed exit, non-optimistic bid/ask entry, quote spread/freshness/transport delay, position loss ceiling, account-wide projected daily loss including unrealized downside and existing reserved risk, margin, leverage and fully funded cash exposure. The result exposes failed assumptions and cash figures. Re-review comparison detects changed intent, stale quotes or expired packet; it is **not** a reusable approval token. A digest is **not a signature**, and an untrusted caller can calculate it.

**Safety boundary:** Inputs are NOT authenticated broker prices, balances, positions, available cash, instrument permissions, sessions or owner identity. The helper has no broker requests, credentials, persistent order-ID reservations, actual approval record, signing, live/demo order route, or state mutation. Both `may_execute_real_order` and `may_execute_paper_order` are always false, even if every hypothetical check passes. The packet must never be used as an execution permission. A stressed stop does not guarantee a maximum loss during a gap.

From `backend`: `PYTHONPATH=. python -m pytest -q tests/test_live_order_review.py`. All test data is synthetic.

## Integration handoff

Keep this isolated from draft PRs #26 (durable reservations), #34 (preview API), #35 (position sizing), and #36 (stop observation) until coordinated. To make a **future** authenticated review workflow, verify eligible provider/account/instrument and quote source; bind an authenticated owner session and immutable per-order review to a durable, single-use reservation, server-side risk recheck and independent audit record. Recheck all conditions after owner approval and immediately before submission; any changed price/quantity/stop, stale quote, expired review, concurrent order or kill-switch transition must require fresh approval. No blanket autonomous live trading. Production deployment requires selected Render workspace, backups, rollback and health verification; no deployment is performed by this PR.


## Adverse executable quote and stressed-equity hardening (25 October 2026)

The disconnected review now **fails** `protective_stop_not_breached` when a BUY quote BID touches/falls below its stop or a SELL quote ASK touches/exceeds its stop. It never infers that a broker placed, executed or honored a stop. For a BUY, hypothetical downside uses the lower of the owner-declared stressed exit and the observed BID; for a SELL it uses the higher of the stressed exit and observed ASK. This worsened downside feeds the position-loss ceiling and projected daily-loss check. Stressed equity (`account_equity_cash - stressed_loss_cash`) must remain positive and must still cover the declared combined margin and leverage. Current-equity-only checks remain independently enforced.

The quote, balance, margin, costs, instrument multiplier, currency conversion and portfolio inventory are **not provider-authenticated**. Even an unbreached stop or a clean review is NOT execution permission. Gaps, slippage, halts, liquidation and fees can exceed this hypothetical stress. No broker request, order, durable reservation, approval record, or database write was added. The reviewer returns `may_execute_paper_order=false` and `may_execute_real_order=false` unconditionally. Test with `PYTHONPATH=. pytest -q tests/test_live_order_review.py`, then exact-head CI before merge consideration.

## Conservative review ceilings (26 October 2026)

The offline preview now rejects quote-policy settings above **3,000 ms maximum observed-quote age** or **1,000 ms maximum observed-to-received transport lag**. A caller cannot relax either limit to 60 seconds. It also marks a hypothetical review as failing if the *declared* position-loss budget exceeds **5% of declared equity**, the declared daily-loss budget exceeds **10% of declared equity**, the declared gross leverage policy exceeds **5×**, or the declared maximum spread tolerance exceeds **100 basis points**. These are conservative fixed ceilings for this research preview, not provider-derived universal limits or an execution strategy. The owner may choose stricter values. A zero-equity or malformed amount already fails validation.

A passing check only means that unauthenticated inputs are internally consistent under these bounds. Actual position exposure, maintenance margin, negative balances, overnight financing, broker stop semantics, gaps, slippage, stale inventory, account currency conversion and cross-process reservations are not independently verified. Even an apparently passing packet remains **non-executable**; per-order owner confirmation and authenticated, atomic server-side risk rechecks are required in any separately designed future live execution workflow.

## Cash-account cost buffer (31 October 2026)

For the disconnected Invest/Stocks ISA BUY preview, `cash_account_fully_funded` now requires **declared existing gross exposure + proposed purchase notional + declared total estimated costs <= declared account equity**. Previously it checked purchase exposure without the estimated cost buffer, allowing a hypothetical cash purchase to appear fully funded even when its declared costs exceeded the remaining equity. The exact-equality boundary is allowed; a one-penny excess fails. Synthetic regressions cover both cash account types, the exact decimal boundary, and a zero-cost case. This is deliberately conservative and may overstate the cash required when `estimated_total_cost_cash` includes future exit costs. It does **not** verify actual available cash, settlement obligations, currency conversion, broker commissions or any real account. It cannot authorize an order; both execution flags remain false.

## Integration reconciliation (31 October 2026)

This branch is rebased as a single isolated change on the then-current `main`, preserving its already-merged executable-quote stop-breach and stressed-equity protections. The PR previously diverged by over 2,000 commits and was marked conflicting; this rebased candidate retains both layers of synthetic regressions and adds the bounded review policies and cash-cost buffer. Review and CI are still required. No broker execution or Render deployment is authorized.

## Realized-gain daily-risk guard (31 October 2026)

The disconnected projected daily-loss check now counts **negative realized and negative unrealized P&L** but never credits positive realized or unrealized gains toward the declared daily risk cap. Previously, a large owner-declared realized profit could offset outstanding reservations and the new stressed loss, allowing a hypothetical review to pass even when those losses alone exceeded the cap. Synthetic regressions cover a declared 1,000-cash realized windfall that must not unlock risk, and a realized loss that must still reduce the remaining budget. This is a deliberately conservative **preview policy**, not a broker-specific daily reset rule or authenticated account ledger. No execution permission, broker connection, production change, or real-data proof is introduced.


## Full packet consistency during re-review (31 October 2026)

`compare_review` now requires the **entire supplied review packet** to equal a deterministic recomputation from the revised intent, original issue/expiry times and the requested review policy. Previously, only the input SHA-256 digest was compared, so local edits to displayed checks, stressed-loss figures, warnings or even the `may_execute_*` fields could leave `review_matches_exact_intent=true`. The new comparison fails closed and requires a new human review for modified, missing or extra packet fields. Synthetic regressions cover those alterations and an untouched packet. This is **not** cryptographic authenticity: a malicious party controlling the unsigned packet and declarations can recompute them; a broker-signed receipt and independent account evidence are still absent. The module remains disconnected and both execution flags remain false.

Follow-up CI repair: review comparison treats bounded, plain-decimal computed cash fields as **numeric equivalents** (e.g. `4.54` and `4.540`) so canonically identical order quantities do not falsely fail. All non-cash packet fields, including nested boolean checks, are compared with JSON type fidelity. This repairs a canonical-decimal regression found in the first full-suite CI run; altered economic values and changed check flags still fail closed.

## Typed packet-shape hardening (31 October 2026)

The disconnected `compare_review` check now compares the fixed review packet schema directly, preserving Python/JSON type distinctions for every field. In particular, a tuple substituted for a `warnings` or `failed_checks` array is no longer silently treated as equal to a list by JSON serialization; `checks` must be a dictionary of exact boolean flags. Unexpected nested structures, including deeply nested values that could previously trigger a serialization `RecursionError`, fail closed with `requires_new_human_review=true` instead of crashing the review comparison. Only the four computed cash fields continue to accept equivalent bounded plain-decimal string representations (for example `2.0` and `2.00`). Synthetic regressions cover tuple coercion, pathological nesting, unchanged packets, boolean tampering and canonical decimal equivalence.

This is an **input-consistency guard**, not authenticated evidence or a signature. A caller controlling the packet and input declarations can still construct matching values. The review remains offline, with both execution flags permanently false; no orders, deployment, or broker verification are implied.

## Cash-account full-margin consistency (1 November 2026)

For the disconnected Trading 212 Invest and Stocks ISA BUY preview, the owner-declared `margin_rate_percent` must now equal **100%**. Previously a lower declared margin rate could understate the preview's combined/stressed margin requirement even while `cash_account_fully_funded` passed. The new `cash_account_full_margin_policy` check fails closed for sub-100% declarations; it does not change the separate cost-inclusive cash-funding rule. Synthetic regressions cover both cash-account categories, discounted rates near zero/50%/just below 100%, and the exact 100% boundary. This is a deliberately conservative modeling consistency rule, **not** an authenticated broker margin requirement or verification of spendable cash. Trading 212 CFD remains unsupported by the official-account check, regardless of this preview rule. No order execution, broker connection, production data change or deployment is enabled.


## Declared entry-versus-quote sanity ceiling (1 November 2026)

The disconnected review now independently fails `declared_entry_deviation_at_most_100bps` when a BUY's owner-declared entry exceeds the quoted ASK by more than 1%, or a SELL's declared entry falls more than 1% below the quoted BID. Exact 100-basis-point boundaries are accepted; a single eight-decimal increment beyond the boundary is rejected. The pre-existing `entry_not_better_than_quote` check still independently rejects unrealistically *favorable* declared entries. Synthetic BUY/SELL boundary tests exercise both checks and retain unconditional non-execution flags.

This 100-bps bound is a deliberately conservative **offline review sanity ceiling**, not a verified Trading 212 order-slippage setting, not an estimate of executable prices, and not evidence of broker-authenticated quotes or balances. Real spreads, fills, costs, slippage, news/session restrictions and stop gaps still require authenticated source-specific evidence. No order route, paid service, production mutation, main merge or deployment is introduced.

## Strict review-packet container validation (1 November 2026)

`compare_review` now rejects non-object review packets and Python `dict` subclasses **before** attempting to read the fingerprint. Previously, a non-dictionary packet could trigger an uncontrolled `AttributeError` instead of the same controlled `ValueError` validation failure used for malformed fingerprints. A subclass could also override `.get()` before the fixed-schema equality check. Six synthetic regressions exercise null, list, tuple, text, numeric and overridden-dictionary inputs; an unchanged plain-dictionary packet still compares without enabling either execution flag.

This is defensive validation of untrusted offline input, **not** an authenticated approval, broker evidence, signature, live order path, profitability finding or deployment. Invalid packets must be rejected and recreated by a human; they must never be interpreted as execution permission.


## Plain order-input validation (1 November 2026)

The disconnected review now rejects non-dictionary order inputs, dictionary subclasses and string subclasses **before** inspecting their fields. Previously, the input normalizer accepted dictionary subclasses and could invoke attacker-defined iteration or indexing methods; identity and decimal fields also accepted string subclasses. Only ordinary JSON-style objects and exact strings are now accepted. Synthetic regressions cover malformed containers, a mapping subclass with hostile accessors, and decimal/identity string subclasses while confirming normal inputs still produce permanently non-executable packets. This is input hardening, **not** broker authentication, strategy validation or execution permission. No real order, dataset, production mutation or Render deployment is involved.
