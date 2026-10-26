"""Deterministic, disconnected quote-tape demo fill scenarios (NOT a broker adapter).

No network, broker orders, storage, data fetching, credentials, P&L or profit claim.
Declared quote depth is NOT authenticated liquidity and fill eligibility is NOT
proof of queue priority or executable fills. Outputs are hypothetical only.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

_PROTOCOL = "offline-demo-quote-tape-scenario-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\\Z")
_SHA = re.compile(r"[0-9a-f]{64}\\Z")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\\.[0-9]{1,8})?\\Z")
_SCOPE = {"provider", "venue", "account_alias", "instrument", "quote_currency",
          "point_value_cash", "max_quote_age_ms", "max_spread_price",
          "adverse_slippage_price", "commission_per_contract_side", "as_of_ms"}
_INTENT = {"client_order_id", "side", "kind", "requested_contracts", "limit_price",
           "submitted_at_ms", "eligible_after_ms", "expires_at_ms",
           "cancel_requested_at_ms", "cancel_effective_at_ms"}
_QUOTE = {"quote_id", "provider", "venue", "account_alias", "instrument",
          "observed_at_ms", "received_at_ms", "bid", "ask", "available_contracts"}
_MAX_MS = 100_000_000_000_000


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != keys:
        raise ValueError("Invalid " + label + " schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _ms(value):
    return type(value) is int and 0 <= value <= _MAX_MS


def _decimal(value, label, *, positive=False):
    if type(value) is not str or _NUMBER.fullmatch(value) is None:
        raise ValueError("Invalid exact " + label)
    d = Decimal(value)
    if positive and d <= 0:
        raise ValueError("Nonpositive " + label)
    return d


def _contracts(value, *, zero=False):
    return type(value) is int and (0 if zero else 1) <= value <= 1_000_000


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _validate_scope(scope):
    _exact(scope, _SCOPE, "scenario scope")
    if not all(_id(scope[k]) for k in ("provider", "venue", "account_alias", "instrument")):
        raise ValueError("Invalid source identity")
    if type(scope["quote_currency"]) is not str or not _CURRENCY.fullmatch(scope["quote_currency"]):
        raise ValueError("Invalid quote currency")
    for k in ("point_value_cash", "max_spread_price", "adverse_slippage_price",
              "commission_per_contract_side"):
        _decimal(scope[k], k, positive=k == "point_value_cash")
    if not _ms(scope["as_of_ms"]) or type(scope["max_quote_age_ms"]) is not int or not (1 <= scope["max_quote_age_ms"] <= 60_000):
        raise ValueError("Invalid quote policy or evaluation clock")


def _validate_quotes(scope, quotes):
    if type(quotes) is not list or len(quotes) > 2_000:
        raise ValueError("Unbounded quote tape")
    seen = set()
    last_observed = -1
    last_received = -1
    for quote in quotes:
        _exact(quote, _QUOTE, "quote")
        if (not _id(quote["quote_id"]) or quote["quote_id"] in seen or
            any(quote[k] != scope[k] for k in ("provider", "venue", "account_alias", "instrument")) or
            not _ms(quote["observed_at_ms"]) or not _ms(quote["received_at_ms"]) or
            quote["observed_at_ms"] <= last_observed or quote["received_at_ms"] <= last_received or
            quote["observed_at_ms"] > quote["received_at_ms"] or
            quote["received_at_ms"] > scope["as_of_ms"] or
            not _contracts(quote["available_contracts"], zero=True)):
            raise ValueError("Duplicate, cross-source, future or non-monotonic quote")
        bid = _decimal(quote["bid"], "bid", positive=True)
        ask = _decimal(quote["ask"], "ask", positive=True)
        if bid > ask:
            raise ValueError("Crossed bid/ask quote")
        seen.add(quote["quote_id"])
        last_observed, last_received = quote["observed_at_ms"], quote["received_at_ms"]


def fingerprint_demo_quote_tape(scope, quotes):
    """Self-declared deterministic receipt; neither signed nor independently frozen."""
    _validate_scope(scope)
    _validate_quotes(scope, quotes)
    return _digest({"protocol": _PROTOCOL, "scope": scope, "quotes": quotes})


def _validate_intent(scope, intent):
    _exact(intent, _INTENT, "demo intent")
    if (not _id(intent["client_order_id"]) or intent["side"] not in ("BUY", "SELL") or
        intent["kind"] not in ("MARKET", "LIMIT") or
        not _contracts(intent["requested_contracts"]) or
        not all(_ms(intent[k]) for k in ("submitted_at_ms", "eligible_after_ms", "expires_at_ms")) or
        not (intent["submitted_at_ms"] <= intent["eligible_after_ms"] < intent["expires_at_ms"]) or
        intent["submitted_at_ms"] > scope["as_of_ms"]):
        raise ValueError("Invalid demo order intent")
    if intent["kind"] == "MARKET":
        if intent["limit_price"] is not None:
            raise ValueError("Market order cannot have limit price")
    else:
        _decimal(intent["limit_price"], "limit price", positive=True)
    requested, effective = intent["cancel_requested_at_ms"], intent["cancel_effective_at_ms"]
    if (requested is None) != (effective is None):
        raise ValueError("Incomplete synthetic cancel chronology")
    if requested is not None and (not _ms(requested) or not _ms(effective) or
                                  not (intent["submitted_at_ms"] <= requested < intent["expires_at_ms"] and requested <= effective <= scope["as_of_ms"])):
        raise ValueError("Invalid synthetic cancel chronology")


def simulate_declared_demo_quote_tape(scope, intent, quotes, expected_tape_sha256):
    """Scenario fills at supplied executable side, bounded by declared depth.

    Cancellation becomes effective at a caller-declared timestamp; a request
    alone does not cancel. Expiry/cancellation win ties with quote receipt.
    Each quote's depth is assumed independently available, with no queue model.
    """
    _validate_scope(scope)
    _validate_intent(scope, intent)
    tape_hash = fingerprint_demo_quote_tape(scope, quotes)
    if type(expected_tape_sha256) is not str or not _SHA.fullmatch(expected_tape_sha256) or tape_hash != expected_tape_sha256:
        raise ValueError("Quote tape digest mismatch; no scenario result")
    with localcontext() as ctx:
        ctx.prec = 60
        spread_cash = slippage_cash = commission_cash = Decimal(0)
        filled = 0
        fills = []
        point_value = Decimal(scope["point_value_cash"])
        max_spread = Decimal(scope["max_spread_price"])
        slip = Decimal(scope["adverse_slippage_price"])
        fee = Decimal(scope["commission_per_contract_side"])
        limit = Decimal(intent["limit_price"]) if intent["kind"] == "LIMIT" else None
        for quote in quotes:
            received = quote["received_at_ms"]
            if received >= intent["expires_at_ms"]:
                break
            if intent["cancel_effective_at_ms"] is not None and received >= intent["cancel_effective_at_ms"]:
                break
            if (received < intent["eligible_after_ms"] or
                quote["observed_at_ms"] <= intent["submitted_at_ms"] or
                received - quote["observed_at_ms"] > scope["max_quote_age_ms"] or
                filled == intent["requested_contracts"]):
                continue
            bid, ask = Decimal(quote["bid"]), Decimal(quote["ask"])
            spread = ask - bid
            if spread > max_spread:
                continue
            price = ask + slip if intent["side"] == "BUY" else bid - slip
            if price <= 0 or (limit is not None and
                              (price > limit if intent["side"] == "BUY" else price < limit)):
                continue
            qty = min(intent["requested_contracts"] - filled, quote["available_contracts"])
            if qty == 0:
                continue
            spread_cash += (spread / 2) * qty * point_value
            slippage_cash += slip * qty * point_value
            commission_cash += fee * qty
            fills.append({"quote_id": quote["quote_id"], "at_ms": received,
                          "contracts": qty, "price": str(price),
                          "source": "DECLARED_DEPTH_HYPOTHETICAL_ONLY"})
            filled += qty
        asof = scope["as_of_ms"]
        if filled == intent["requested_contracts"]:
            status = "HYPOTHETICALLY_FILLED"
        elif (intent["cancel_effective_at_ms"] is not None and
              intent["cancel_effective_at_ms"] <= asof and
              intent["cancel_effective_at_ms"] < intent["expires_at_ms"]):
            status = "SYNTHETIC_CANCELED_WITH_EXPOSURE" if filled else "SYNTHETIC_CANCELED_UNFILLED"
        elif intent["expires_at_ms"] <= asof:
            status = "EXPIRED_WITH_EXPOSURE" if filled else "EXPIRED_UNFILLED"
        else:
            status = "PARTIAL_UNRESOLVED" if filled else "PENDING_UNRESOLVED"
        result = {"coverage": "SELF_DECLARED_OFFLINE_HYPOTHETICAL_ONLY", "status": status,
                  "client_order_id": intent["client_order_id"],
                  "requested_contracts": intent["requested_contracts"],
                  "hypothetical_filled_contracts": filled,
                  "remaining_contracts": intent["requested_contracts"] - filled,
                  "fills": fills, "spread_cost_cash": str(spread_cash),
                  "adverse_slippage_cash": str(slippage_cash),
                  "commission_cash": str(commission_cash),
                  "total_entry_cost_cash": str(spread_cash + slippage_cash + commission_cash),
                  "quote_tape_sha256": tape_hash,
                  "scenario_sha256": _digest({"protocol": _PROTOCOL, "scope": scope,
                                               "intent": intent, "quote_tape_sha256": tape_hash}),
                  "may_execute_demo_order": False, "may_execute_real_order": False,
                  "warnings": ["Declared quote depth does not prove available liquidity or queue priority.",
                               "A matching digest is not source authentication or independent preregistration.",
                               "No exits, CFD financing, FX settlement, market halts or actual broker fills are modeled.",
                               "Unknown or omitted quotes/fills are not proof of no exposure or profitability."]}
        return result
