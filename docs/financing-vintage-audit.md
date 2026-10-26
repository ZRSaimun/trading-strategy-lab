# CFD financing point-in-time revision audit — offline research only

The isolated, stdlib-only module at `backend/app/financing_vintage_audit.py` has no broker connection, database write, archive access, order path, or trading-profit calculation.

## Research problem

Historical backtests can accidentally use a financing charge **corrected after** the simulated decision time. This creates lookahead bias even if price candles have correct timestamps. The audit binds one caller-declared provider, venue, instrument, account alias, position, settlement currency and schedule to versioned financing receipts. For each strictly increasing cutoff, it selects only revisions whose **publication and ingestion** clocks are both no later than the cutoff. A later correction cannot silently change an earlier snapshot.

Input: an exact-key `scope` with `provider`, `venue`, `instrument`, `account_alias`, `position_id`, `settlement_currency`, `opened_at`, `closed_at`, `audit_asof`, and sorted `required_rollovers`; a list of receipt revisions with unique `receipt_id`, matching source identity, `rollover_at`, consecutive 1-based `revision`, `published_at`, `ingested_at`, `statement_sha256` and signed `amount_currency`; and sorted unique `cutoffs`. Clocks are bounded UTC epoch seconds; amounts are canonical decimal strings with at most two fractional digits, positive=debit and negative=credit.

The audit rejects missing/duplicate revision sequence numbers, replayed IDs, foreign source/position/currency, impossible clocks, nonmonotonic revision publication or ingestion, malformed hashes/amounts, unknown fields and unbounded inputs. A missing declared rollover receipt yields `WITHHELD_MISSING_RECEIPTS` and a null **entire snapshot** total; no due declared rollovers also yields a null total. Only `MATCHED_SELF_DECLARED` exposes the declared two-decimal total. Selected receipt revisions and missing timestamps are reported. The order-independent SHA-256 is a diagnostic over supplied declarations, **not** a trusted timestamp or evidence of independent preregistration.

## Important limitations

Every timestamp, calendar event, hash and receipt is supplied by the caller; none is independently authenticated. This does not establish the broker's true long/short funding rates, overnight calendar, weekend/triple swaps, contract multiplier, FX conversion, daylight-saving/holiday convention, complete statements, fill price or profitability. The audit always reports `source_authenticated=false`, `calendar_complete_verified=false`, `realized_net_cost_verified=false`, `verified_profitability=false` and `may_execute_order=false`. It cannot justify enabling paper or real order submission.

Before integrating into frozen net-of-cost walk-forward evaluation, independently verify permitted broker statement provenance and publication clocks, reconcile complete position-level financing and executable quotes, register strategy/splits/cost rules **before** outcomes, and keep untouched holdouts isolated. No Trading 212 CFD trading API is assumed.

Synthetic-only test command, from repository root:

```bash
cd backend
PYTHONPATH=. python -m pytest -q tests/test_financing_vintage_audit.py
```

No licensed archives, paid services, secrets, or brokerage orders are involved.
