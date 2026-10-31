# Offline point-in-time CFD financing availability census

`backend/app/declared_financing_asof_census.py` is a disconnected, standard-library-only **research gate** for self-declared rollover events, financing bookings and cash postings. It does not contact a broker, read licensed archives, route demo/live orders, authenticate statements or calculate strategy profitability.

For a strictly increasing list of UTC cutoffs, it reports a complete signed net cash delta **only when every declared rollover due by that cutoff has both a matching financing event and cash receipt observed by the cutoff**. Unknown or delayed events result in `INCOMPLETE_AS_OF` with `net_cash_delta: null`, never an optimistic partial cost. A cutoff with no declared due rollovers returns `NO_DUE_YET_UNVERIFIED` with null cost. Exact-decimal cash arithmetic and strict source identity (provider, venue, account, instrument, position, currency), receipt chronology, ID uniqueness, bounds and schemas are enforced. The final result never grants order permissions.

Example from `backend/`:

```bash
PYTHONPATH=. python -m pytest -q tests/test_declared_financing_asof_census.py
```

**Trust limitations:** All provider/account/position identities, SHA-256 strings, due-rollover populations and observation clocks are supplied by the caller. A digest string is not a broker signature. A self-declared calendar can omit real rollovers, and a historical receipt's `observed_at_utc` may be falsely backdated. The module checks internal consistency only; it cannot prove a historical strategy knew the financing costs, cannot establish live bid/ask spreads or financing rates, and cannot certify untouched holdouts or profits. Independently verify licensed source bytes, broker-authenticated statements and external append-only availability timestamps before using these figures as research evidence. In particular, do not treat a complete self-declared snapshot as permission to execute orders.
