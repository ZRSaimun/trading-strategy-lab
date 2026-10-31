"""Disconnected, fail-closed review of changes to declared paper risk policies.

This is a structural review only. It neither authenticates a policy nor writes
it to storage, resets a circuit breaker, or grants permission to send orders.
A deployment must enforce any policy transition atomically with its durable
risk reservations, order-intent registry and audit trail.
"""

from decimal import Decimal
import hashlib
import json
import re

_MAX_MS = 8_640_000_000_000_000
_MAX_REV = 2**53 - 1
_CASH_MAX = Decimal("1000000000000000")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_MONEY = re.compile(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?\Z")
_FIELDS = frozenset({
    "version", "account_alias", "provider", "currency", "revision",
    "effective_at_ms", "emergency_latched", "max_position_loss_cash",
    "max_daily_loss_cash", "max_gross_notional_cash", "max_margin_cash",
    "max_gross_leverage", "max_margin_fraction", "max_quote_age_ms",
    "max_transport_lag_ms", "max_spread_bps", "max_open_or_pending_orders",
    "max_orders_per_symbol", "max_orders_per_hour", "max_orders_per_day",
    "min_order_cooldown_ms", "max_consecutive_losses",
})
_MONEY_LIMITS = {
    "max_position_loss_cash": _CASH_MAX,
    "max_daily_loss_cash": _CASH_MAX,
    "max_gross_notional_cash": _CASH_MAX,
    "max_margin_cash": _CASH_MAX,
    "max_gross_leverage": Decimal("100"),
    "max_margin_fraction": Decimal("1"),
    "max_spread_bps": Decimal("10000"),
}
_INT_LIMITS = {
    "max_quote_age_ms": (100, 3000),
    "max_transport_lag_ms": (0, 1000),
    "max_open_or_pending_orders": (1, 500),
    "max_orders_per_symbol": (1, 100),
    "max_orders_per_hour": (1, 1000),
    "max_orders_per_day": (1, 10000),
    "min_order_cooldown_ms": (0, 86_400_000),
    "max_consecutive_losses": (1, 100),
}
_LOWER_IS_STRICTER = tuple(_MONEY_LIMITS) + tuple(k for k in _INT_LIMITS if k != "min_order_cooldown_ms")


def _validate(doc):
    if type(doc) is not dict or set(doc) != _FIELDS:
        raise ValueError("Risk policy must have exactly the required fields")
    if type(doc["version"]) is not int or doc["version"] != 1:
        raise ValueError("Unsupported risk policy version")
    for field in ("account_alias", "provider"):
        if type(doc[field]) is not str or not _ID.fullmatch(doc[field]):
            raise ValueError("Invalid risk policy identity")
    if type(doc["currency"]) is not str or not re.fullmatch(r"[A-Z]{3}", doc["currency"]):
        raise ValueError("Invalid risk policy currency")
    for field, maximum in (("revision", _MAX_REV), ("effective_at_ms", _MAX_MS)):
        if type(doc[field]) is not int or not 0 <= doc[field] <= maximum:
            raise ValueError("Invalid risk policy revision/time")
    if type(doc["emergency_latched"]) is not bool:
        raise ValueError("Invalid risk policy emergency latch")
    values = {}
    for field, maximum in _MONEY_LIMITS.items():
        raw = doc[field]
        if type(raw) is not str or not _MONEY.fullmatch(raw):
            raise ValueError("Risk caps require bounded, unsigned decimal strings")
        amount = Decimal(raw)
        if not 0 < amount <= maximum:
            raise ValueError("Invalid risk cap")
        values[field] = amount
    for field, (minimum, maximum) in _INT_LIMITS.items():
        raw = doc[field]
        if type(raw) is not int or not minimum <= raw <= maximum:
            raise ValueError("Invalid risk policy integer cap")
        values[field] = raw
    if (values["max_position_loss_cash"] > values["max_daily_loss_cash"]
        or values["max_orders_per_symbol"] > values["max_open_or_pending_orders"]
        or values["max_orders_per_hour"] > values["max_orders_per_day"]):
        raise ValueError("Inconsistent risk policy caps")
    # Return only validated values; never normalize or mutate caller objects.
    return values


def review_paper_risk_policy_tightening(previous, proposed, *, now_ms):
    """Review a single declared policy transition without ever authorizing it.

    A *passing* review means only that a structurally valid proposed policy is
    no weaker in any configured dimension. Source, completeness, revision and
    clock are NOT authenticated by this function. Relaxations require a distinct
    owner-authenticated, broker-reconciled, audited workflow not provided here.
    """
    if type(now_ms) is not int or not 0 <= now_ms <= _MAX_MS:
        raise ValueError("Invalid trusted server clock")
    old = _validate(previous)
    new = _validate(proposed)
    if (previous["account_alias"], previous["provider"], previous["currency"]) != (
        proposed["account_alias"], proposed["provider"], proposed["currency"]
    ):
        raise ValueError("Risk policy account/provider/currency changed")
    if previous["effective_at_ms"] > now_ms:
        raise ValueError("Previous policy is future-dated")
    if previous["revision"] == _MAX_REV:
        raise ValueError("Policy revision exhausted")
    checks = {
        "next_revision": proposed["revision"] == previous["revision"] + 1,
        "effective_time_monotonic": (previous["effective_at_ms"] < proposed["effective_at_ms"] <= now_ms),
        "emergency_latch_never_cleared": (not previous["emergency_latched"] or proposed["emergency_latched"]),
        "cooldown_not_shortened": new["min_order_cooldown_ms"] >= old["min_order_cooldown_ms"],
    }
    for field in _LOWER_IS_STRICTER:
        checks[field + "_not_relaxed"] = new[field] <= old[field]
    # Hash the complete declared transition (including identity, revision and
    # timestamps) for a diagnostic review trail. This is NOT a signature.
    canonical = json.dumps({"schema": "paper-risk-policy-tightening-v1", "previous": previous,
                            "proposed": proposed, "now_ms": now_ms},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                           allow_nan=False)
    failed = sorted(k for k, passed in checks.items() if not passed)
    return {
        "status": "HOLD_RECONCILIATION",
        "assumption_checks_pass": not failed,
        "checks": checks,
        "failed_checks": failed,
        "review_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "source_authenticated": False,
        "policy_persisted": False,
        "owner_approval_recorded": False,
        "may_clear_emergency_latch": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warnings": [
            "Policies and time are caller-declared; this is not an authenticated or durable policy update.",
            "A passing structural review does not authorize an order or a risk-policy change.",
            "A live policy change needs atomic persistence, verified inventory, audit and human authorization.",
        ],
    }
