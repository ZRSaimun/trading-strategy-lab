"""Disconnected, fail-closed paper protective-stop observation (NO order execution).

The caller supplies untrusted snapshots. A quote passing these structural checks
is NOT authenticated and must not be used for broker or paper order submission.
The module never changes journal/reservation state, fetches quotes or sends orders.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import re

_MAX_TIME = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")


@dataclass(frozen=True)
class PaperQuote:
    instrument: str
    provider: str
    venue: str
    quote_id: str
    sequence: int
    bid: str
    ask: str
    observed_at_ms: int
    received_at_ms: int


@dataclass(frozen=True)
class PaperStop:
    position_id: str
    instrument: str
    provider: str
    venue: str
    side: str  # LONG or SHORT; this is an existing hypothetical position
    entry_price: str
    protective_stop: str
    quantity: str
    point_value_cash: str
    assumed_exit_cost_cash: str = "0"


@dataclass(frozen=True)
class QuotePolicy:
    max_quote_age_ms: int = 3000
    max_transport_lag_ms: int = 1000
    max_spread_bps: str = "20"
    previous_sequence: int | None = None
    previous_observed_at_ms: int | None = None
    previous_quote_id: str | None = None


def _decimal(raw: str, label: str, *, positive: bool = True) -> Decimal:
    # Require lossless decimal strings: floats and booleans silently round money.
    if not isinstance(raw, str) or not re.fullmatch(r"(?:0|[1-9]\d{0,29})(?:\.\d{1,18})?", raw):
        raise ValueError(f"Invalid {label}: expected bounded nonnegative decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not value.is_finite() or (value <= 0 if positive else value < 0):
        raise ValueError(f"Invalid {label}: nonpositive amount")
    return value


def _id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {label}")


def _source(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SOURCE.fullmatch(value):
        raise ValueError(f"Invalid {label}")


def _time(value: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_TIME:
        raise ValueError(f"Invalid {label}")


def observe_paper_stop(stop: PaperStop, quote: PaperQuote, policy: QuotePolicy, *, server_now_ms: int) -> dict:
    """Return a *non-executable* stop observation with exact decimal arithmetic.

    `server_now_ms` must be injected by a trusted server clock, not a client.
    All checks are structural; origin and actual executability remain unknown.
    A stop breach is an alert/reconciliation candidate, NEVER a fill or order.
    """
    _time(server_now_ms, "server clock")
    _id(stop.position_id, "position ID")
    _id(quote.quote_id, "quote ID")
    for name, value in (("instrument", stop.instrument), ("provider", stop.provider),
                        ("venue", stop.venue), ("quote instrument", quote.instrument),
                        ("quote provider", quote.provider), ("quote venue", quote.venue)):
        _source(value, name)
    if stop.side not in ("LONG", "SHORT"):
        raise ValueError("Invalid position side")
    for name, value in (("sequence", quote.sequence), ("max quote age", policy.max_quote_age_ms),
                        ("max transport lag", policy.max_transport_lag_ms)):
        _time(value, name)
    if policy.max_quote_age_ms < 100 or policy.max_transport_lag_ms > 60_000:
        raise ValueError("Invalid quote timing policy")
    for name, value in (("observed time", quote.observed_at_ms), ("received time", quote.received_at_ms)):
        _time(value, name)
    if policy.previous_sequence is not None:
        _time(policy.previous_sequence, "previous sequence")
    if policy.previous_observed_at_ms is not None:
        _time(policy.previous_observed_at_ms, "previous observed time")
    if policy.previous_quote_id is not None:
        _id(policy.previous_quote_id, "previous quote ID")

    with localcontext() as ctx:
        ctx.prec = 100
        bid = _decimal(quote.bid, "bid")
        ask = _decimal(quote.ask, "ask")
        entry = _decimal(stop.entry_price, "entry")
        protective = _decimal(stop.protective_stop, "protective stop")
        quantity = _decimal(stop.quantity, "quantity")
        point_value = _decimal(stop.point_value_cash, "point value")
        cost = _decimal(stop.assumed_exit_cost_cash, "exit cost", positive=False)
        max_spread = _decimal(policy.max_spread_bps, "max spread")
        if max_spread > 10_000:
            raise ValueError("Invalid max spread")
        if (stop.side == "LONG" and protective >= entry) or (stop.side == "SHORT" and protective <= entry):
            raise ValueError("Protective stop is on the wrong side of entry")

        timestamp_order = quote.observed_at_ms <= quote.received_at_ms <= server_now_ms
        checks = {
            "exact_source_identity": (stop.instrument, stop.provider, stop.venue) == (
                quote.instrument, quote.provider, quote.venue),
            "valid_bid_ask": ask > bid,
            "timestamp_order": timestamp_order,
            "fresh_quote": timestamp_order and server_now_ms - quote.observed_at_ms <= policy.max_quote_age_ms,
            "transport_lag": timestamp_order and quote.received_at_ms - quote.observed_at_ms <= policy.max_transport_lag_ms,
            "sequence_increases": policy.previous_sequence is None or quote.sequence > policy.previous_sequence,
            "observation_time_increases": (policy.previous_observed_at_ms is None or
                                           quote.observed_at_ms > policy.previous_observed_at_ms),
            "new_quote_id": policy.previous_quote_id is None or quote.quote_id != policy.previous_quote_id,
        }
        spread = ((ask - bid) / bid) * Decimal(10_000) if checks["valid_bid_ask"] else None
        checks["spread_within_limit"] = spread is not None and spread <= max_spread
        structurally_valid = all(checks.values())
        # Long stops are triggered by the sellable BID; short stops by the
        # buy-to-cover ASK. Never substitute midpoint or historical bid bars.
        executable_side = bid if stop.side == "LONG" else ask
        breached = structurally_valid and (executable_side <= protective if stop.side == "LONG"
                                             else executable_side >= protective)
        pnl = ((executable_side - entry) if stop.side == "LONG" else (entry - executable_side)) * quantity * point_value - cost
        # A worse quote than the stop is a gap/slippage warning, not a promise
        # of a fill at either price. Do not produce a P&L on rejected quotes.
        quote_hash = hashlib.sha256((quote.provider + "\x00" + quote.venue + "\x00" +
                                     quote.instrument + "\x00" + quote.quote_id).encode("utf-8")).hexdigest()
        return {
            "structural_checks_pass": structurally_valid,
            "checks": checks,
            "failed_checks": [key for key, passed in checks.items() if not passed],
            "spread_bps": str(spread) if spread is not None else None,
            "stop_breach_observed": breached,
            "candidate_exit_side": "BID" if stop.side == "LONG" else "ASK",
            "candidate_exit_price": str(executable_side) if breached else None,
            "candidate_pnl_cash_before_unmodeled_fees": str(pnl) if breached else None,
            "adverse_stop_gap": bool(breached and (executable_side < protective if stop.side == "LONG"
                                                    else executable_side > protective)),
            "quote_identity_sha256": quote_hash if structurally_valid else None,
            "quote_authenticated": False,
            "position_authenticated": False,
            "broker_stop_accepted": False,
            "paper_fill_recorded": False,
            "may_execute_paper_order": False,
            "may_execute_real_order": False,
            "requires_human_reconciliation": breached or not structurally_valid,
            "warnings": [
                "Quote and position are untrusted caller inputs, NOT broker-authenticated.",
                "A breached stop is not proof of an executable price or a broker fill.",
                "Gaps, spreads, market halts, FX conversion and additional costs can increase loss.",
                "No order is placed; journal, risk reservations and circuit breakers are unchanged.",
            ],
        }
