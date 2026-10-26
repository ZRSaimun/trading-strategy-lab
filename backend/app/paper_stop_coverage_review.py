"""Disconnected paper-only stop coverage review; never authorizes an order.

All snapshots are caller-declared and UNAUTHENTICATED. A matching review is not
proof that a broker accepted a stop or that any stop will fill at its price.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?\Z")
_MAX_MS = 8_640_000_000_000_000


@dataclass(frozen=True)
class PaperOpenPosition:
    account_id: str
    position_id: str
    instrument: str
    provider: str
    venue: str
    side: str  # LONG or SHORT
    quantity: str  # remaining OPEN quantity, not cumulative fills
    entry_price: str
    point_value_cash: str
    max_declared_loss_cash: str
    revision: int
    observed_at_ms: int


@dataclass(frozen=True)
class PaperStopAcknowledgement:
    order_id: str
    account_id: str
    position_id: str
    instrument: str
    provider: str
    venue: str
    side: str  # SELL to close LONG; BUY to close SHORT
    reduce_only: bool
    status: str  # ACTIVE required; PENDING/UNKNOWN never count
    remaining_quantity: str
    already_executed_quantity: str
    stop_price: str
    position_revision: int
    observed_at_ms: int
    acknowledged_at_ms: int


@dataclass(frozen=True)
class CoveragePolicy:
    max_snapshot_age_ms: int = 3000
    assumed_exit_cost_cash: str = "0"
    adverse_stress_price: str = "0"  # zero means NO stress evidence: always fail review


def _identifier(value: str, label: str, pattern: re.Pattern) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}")


def _decimal(value: str, label: str, *, positive: bool = True) -> Decimal:
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        raise ValueError(f"Invalid {label}: bounded decimal string required")
    result = Decimal(value)
    if result <= 0 if positive else result < 0:
        raise ValueError(f"Invalid {label}")
    return result


def _int(value: int, label: str, *, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= _MAX_MS:
        raise ValueError(f"Invalid {label}")


def review_paper_stop_coverage(
    position: PaperOpenPosition,
    stops: tuple[PaperStopAcknowledgement, ...],
    policy: CoveragePolicy,
    *,
    server_now_ms: int,
) -> dict:
    """Review a declared snapshot; result is ALWAYS HOLD_RECONCILIATION.

    No I/O, broker access, database mutation, reservation release, or execution.
    Callers must independently authenticate and reconcile position/stop state.
    """
    _int(server_now_ms, "server clock")
    _int(position.revision, "position revision", minimum=1)
    _int(position.observed_at_ms, "position observation")
    _int(policy.max_snapshot_age_ms, "snapshot-age policy", minimum=100)
    if policy.max_snapshot_age_ms > 3000:
        raise ValueError("Snapshot-age policy exceeds hard 3-second limit")
    if not isinstance(stops, tuple) or len(stops) > 8:
        raise ValueError("Expected bounded tuple of stop acknowledgements")
    for label, value in (("account", position.account_id), ("position", position.position_id)):
        _identifier(value, label, _ID)
    for label, value in (("instrument", position.instrument), ("provider", position.provider),
                         ("venue", position.venue)):
        _identifier(value, label, _SOURCE)
    if position.side not in ("LONG", "SHORT"):
        raise ValueError("Invalid position side")
    with localcontext() as ctx:
        ctx.prec = 200
        qty = _decimal(position.quantity, "open quantity")
        entry = _decimal(position.entry_price, "entry price")
        point_value = _decimal(position.point_value_cash, "point value")
        max_loss = _decimal(position.max_declared_loss_cash, "loss cap")
        exit_cost = _decimal(policy.assumed_exit_cost_cash, "exit cost", positive=False)
        stress = _decimal(policy.adverse_stress_price, "adverse stress", positive=False)
        checks = {
            "position_snapshot_fresh": position.observed_at_ms <= server_now_ms and
            server_now_ms - position.observed_at_ms <= policy.max_snapshot_age_ms,
            "exactly_one_stop": len(stops) == 1,
        }
        seen: set[str] = set()
        stop_prices: list[Decimal] = []
        for index, stop in enumerate(stops):
            prefix = f"stop_{index}_"
            _identifier(stop.order_id, "stop order ID", _ID)
            for label, value in (("account", stop.account_id), ("position", stop.position_id)):
                _identifier(value, label, _ID)
            for label, value in (("instrument", stop.instrument), ("provider", stop.provider),
                                 ("venue", stop.venue)):
                _identifier(value, label, _SOURCE)
            _int(stop.position_revision, "stop position revision", minimum=1)
            _int(stop.observed_at_ms, "stop observed time")
            _int(stop.acknowledged_at_ms, "stop acknowledgement time")
            remaining = _decimal(stop.remaining_quantity, "stop remaining quantity", positive=False)
            executed = _decimal(stop.already_executed_quantity, "stop executed quantity", positive=False)
            stop_price = _decimal(stop.stop_price, "stop price")
            stop_prices.append(stop_price)
            checks[prefix + "unique_order_id"] = stop.order_id not in seen
            seen.add(stop.order_id)
            checks[prefix + "identity_matches"] = (
                stop.account_id, stop.position_id, stop.instrument, stop.provider, stop.venue
            ) == (position.account_id, position.position_id, position.instrument,
                  position.provider, position.venue)
            checks[prefix + "close_side"] = stop.side == ("SELL" if position.side == "LONG" else "BUY")
            checks[prefix + "reduce_only"] = type(stop.reduce_only) is bool and stop.reduce_only
            checks[prefix + "active"] = stop.status == "ACTIVE"
            checks[prefix + "revision_matches"] = stop.position_revision == position.revision
            checks[prefix + "fresh_observation"] = stop.observed_at_ms <= server_now_ms and (
                server_now_ms - stop.observed_at_ms <= policy.max_snapshot_age_ms)
            checks[prefix + "acknowledgement_order"] = (
                stop.acknowledged_at_ms <= stop.observed_at_ms <= server_now_ms)
            checks[prefix + "no_partial_execution"] = executed == 0
            checks[prefix + "exact_remaining_coverage"] = remaining == qty
        # A stop price is not a guaranteed fill. Apply a separately declared
        # adverse stress (worse than stop), never the optimistic stop alone.
        checks["stress_supplied"] = stress > 0
        if stop_prices:
            stressed_exit = min(stress, *stop_prices) if position.side == "LONG" else max(stress, *stop_prices)
            downside = max(Decimal(0), (entry - stressed_exit if position.side == "LONG"
                                         else stressed_exit - entry)) * qty * point_value + exit_cost
            checks["declared_stressed_loss_within_cap"] = stress > 0 and downside <= max_loss
        else:
            downside = None
            checks["declared_stressed_loss_within_cap"] = False
        structural = all(checks.values())
        receipt = hashlib.sha256(json.dumps({
            "position": position.__dict__, "stops": [stop.__dict__ for stop in stops],
            "policy": policy.__dict__, "server_now_ms": server_now_ms,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "decision": "HOLD_RECONCILIATION",
            "structural_coverage_match": structural,
            "checks": checks,
            "failed_checks": [key for key, passed in checks.items() if not passed],
            "declared_stressed_loss_cash": str(downside) if downside is not None else None,
            "review_fingerprint_sha256": receipt,
            "broker_state_authenticated": False,
            "stop_execution_guaranteed": False,
            "may_release_risk_reservation": False,
            "may_execute_paper_order": False,
            "may_execute_real_order": False,
            "requires_human_reconciliation": True,
        }
