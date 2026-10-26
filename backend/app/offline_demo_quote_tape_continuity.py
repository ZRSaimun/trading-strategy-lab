"""Causal continuity check for two caller-declared offline demo quote tapes.

Not a broker adapter, independently authenticated data, or trading permission.
The check cannot detect quote omissions shared by both declarations.
"""
from __future__ import annotations

from decimal import Decimal

from app.offline_demo_quote_tape_simulator import (
    _validate_intent, _validate_quotes, _validate_scope,
    fingerprint_demo_quote_tape, simulate_declared_demo_quote_tape,
)

_CANCEL_FIELDS = frozenset({"cancel_requested_at_ms", "cancel_effective_at_ms"})


def audit_declared_demo_quote_tape_continuity(
    earlier_scope, earlier_intent, earlier_quotes, earlier_tape_sha256,
    later_scope, later_intent, later_quotes, later_tape_sha256,
):
    """Reject revisions that rewrite a prior as-of view or use backfilled quotes.

    The earlier quote tape must be an exact prefix of the later one. Only quotes
    received strictly after the earlier cutoff may be appended. The order and
    pricing/risk policy are immutable; a newly declared cancellation must have
    been requested after the earlier cutoff. Both scenarios are recomputed from
    scratch, and earlier hypothetical fills must survive as an exact prefix.
    """
    _validate_scope(earlier_scope)
    _validate_scope(later_scope)
    _validate_intent(earlier_scope, earlier_intent)
    _validate_intent(later_scope, later_intent)
    _validate_quotes(earlier_scope, earlier_quotes)
    _validate_quotes(later_scope, later_quotes)

    cutoff = earlier_scope["as_of_ms"]
    if later_scope["as_of_ms"] <= cutoff:
        raise ValueError("Evaluation cutoffs must strictly advance")
    if {k: v for k, v in earlier_scope.items() if k != "as_of_ms"} != {
        k: v for k, v in later_scope.items() if k != "as_of_ms"
    }:
        raise ValueError("Source identity or execution-cost policy changed")
    if {k: v for k, v in earlier_intent.items() if k not in _CANCEL_FIELDS} != {
        k: v for k, v in later_intent.items() if k not in _CANCEL_FIELDS
    }:
        raise ValueError("Previously declared order intent changed")
    previous_cancel = tuple(earlier_intent[k] for k in sorted(_CANCEL_FIELDS))
    current_cancel = tuple(later_intent[k] for k in sorted(_CANCEL_FIELDS))
    if previous_cancel != current_cancel:
        if (earlier_intent["cancel_requested_at_ms"] is not None
                or later_intent["cancel_requested_at_ms"] is None
                or later_intent["cancel_requested_at_ms"] <= cutoff):
            raise ValueError("Cancellation changed or was backdated")

    if len(later_quotes) < len(earlier_quotes) or later_quotes[:len(earlier_quotes)] != earlier_quotes:
        raise ValueError("Historical quote tape was truncated or rewritten")
    if any(q["received_at_ms"] <= cutoff for q in later_quotes[len(earlier_quotes):]):
        raise ValueError("Newly disclosed quote was available at earlier cutoff")

    earlier = simulate_declared_demo_quote_tape(
        earlier_scope, earlier_intent, earlier_quotes, earlier_tape_sha256)
    later = simulate_declared_demo_quote_tape(
        later_scope, later_intent, later_quotes, later_tape_sha256)
    prior_fills = earlier["fills"]
    if (later["fills"][:len(prior_fills)] != prior_fills
            or later["hypothetical_filled_contracts"] < earlier["hypothetical_filled_contracts"]
            or any(Decimal(later[field]) < Decimal(earlier[field]) for field in (
                "spread_cost_cash", "adverse_slippage_cash", "commission_cash",
                "total_entry_cost_cash"))):
        raise ValueError("Earlier hypothetical fills or entry costs changed")

    return {
        "engine": "offline-demo-quote-tape-continuity-v1",
        "status": "DECLARED_CAUSAL_PREFIX_MATCH_ONLY",
        "earlier_as_of_ms": cutoff,
        "later_as_of_ms": later_scope["as_of_ms"],
        "earlier_tape_sha256": fingerprint_demo_quote_tape(earlier_scope, earlier_quotes),
        "later_tape_sha256": fingerprint_demo_quote_tape(later_scope, later_quotes),
        "earlier_quote_count": len(earlier_quotes),
        "later_quote_count": len(later_quotes),
        "earlier_hypothetical_filled_contracts": earlier["hypothetical_filled_contracts"],
        "later_hypothetical_filled_contracts": later["hypothetical_filled_contracts"],
        "new_hypothetical_filled_contracts": (
            later["hypothetical_filled_contracts"] - earlier["hypothetical_filled_contracts"]),
        "prior_fills_preserved": True,
        "independent_quote_custody_verified": False,
        "broker_fills_authenticated": False,
        "broker_quote_population_complete": False,
        "manual_broker_reconciliation_required": True,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
    }
