"""Fail-closed, stateless quote and circuit-breaker preview for future paper orders.

This module does not reserve client order IDs, authenticate quote origins, persist
circuit-breaker state or permit a live/demo order. Server time is injected by the
caller so clients cannot make stale quotes look fresh by forging 'now'.
"""
import math
import re
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class QuoteSnapshot(Strict):
    instrument: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    venue: str = Field(min_length=1, max_length=80)
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    observed_at_ms: int = Field(ge=0, le=8_640_000_000_000_000)
    received_at_ms: int = Field(ge=0, le=8_640_000_000_000_000)


class OrderGateContext(Strict):
    quote: QuoteSnapshot
    expected_instrument: str = Field(min_length=1, max_length=80)
    expected_provider: str = Field(min_length=1, max_length=80)
    expected_venue: str = Field(min_length=1, max_length=80)
    max_quote_age_ms: int = Field(default=3000, ge=100, le=60_000)
    max_transport_lag_ms: int = Field(default=1000, ge=0, le=60_000)
    max_spread_bps: float = Field(default=20, gt=0, le=10_000)
    client_order_id: str = Field(min_length=8, max_length=80)
    prior_client_order_ids: list[str] = Field(default_factory=list, max_length=200)
    existing_open_or_pending_order: bool = False
    kill_switch_active: bool = True
    market_session_open: bool = False
    daily_realized_pnl_cash: float = 0
    # Account-wide, owner-declared cash amounts in the same account currency.
    # Floating profits do not offset downside; reserved risk is incremental
    # potential loss beyond the currently marked unrealized P&L.
    daily_unrealized_pnl_cash: float = 0
    other_positions_reserved_stress_loss_cash: float = Field(default=0, ge=0)
    # Owner-declared, incremental reservations from OTHER open/pending positions.
    # Zero is an unknown default, not proof of zero broker exposure.
    other_positions_reserved_margin_cash: float = Field(default=0, ge=0)
    other_positions_gross_notional_cash: float = Field(default=0, ge=0)
    max_daily_loss_cash: float = Field(gt=0)
    # Required for a passing ORDER preview; None preserves schema compatibility
    # but fails closed until a separate per-position stressed-loss cap is given.
    max_position_loss_cash: float | None = Field(default=None, gt=0)
    consecutive_losses: int = Field(default=0, ge=0)
    max_consecutive_losses: int = Field(default=3, ge=1, le=100)
    owner_confirmed_this_order: bool = False

    @model_validator(mode='after')
    def validate_order_ids(self):
        pattern = r'[A-Za-z0-9][A-Za-z0-9._:-]{7,79}'
        if not re.fullmatch(pattern, self.client_order_id):
            raise ValueError('Invalid client order ID')
        if any(not re.fullmatch(pattern, value) for value in self.prior_client_order_ids):
            raise ValueError('Invalid prior client order ID')
        return self


def evaluate_gate(context: OrderGateContext, now_ms: int) -> dict:
    """Pure, zero-side-effect gate. `now_ms` MUST come from trusted server clock."""
    if type(now_ms) is not int or now_ms < 0 or now_ms > 8_640_000_000_000_000:
        raise ValueError('Invalid server evaluation time')
    q = context.quote
    checks: dict[str, bool] = {}
    checks['exact_source_identity'] = (
        q.instrument == context.expected_instrument
        and q.provider == context.expected_provider
        and q.venue == context.expected_venue
    )
    checks['valid_bid_ask'] = q.ask > q.bid
    # Use bid as the denominator; avoid adding very large prices and report
    # arithmetic overflow as a failed check, not a zero-spread pass.
    spread_bps = ((q.ask / q.bid) - 1.0) * 10_000.0 if checks['valid_bid_ask'] else None
    checks['finite_spread'] = (spread_bps is not None and math.isfinite(spread_bps)
                               and spread_bps > 0)
    checks['spread_within_limit'] = (checks['finite_spread']
                                     and spread_bps <= context.max_spread_bps)
    checks['timestamp_order'] = (q.observed_at_ms <= q.received_at_ms <= now_ms)
    checks['quote_fresh'] = (checks['timestamp_order']
                             and now_ms - q.observed_at_ms <= context.max_quote_age_ms)
    checks['transport_lag_acceptable'] = (checks['timestamp_order']
                                          and q.received_at_ms - q.observed_at_ms
                                          <= context.max_transport_lag_ms)
    checks['new_client_order_id'] = context.client_order_id not in context.prior_client_order_ids
    checks['no_existing_order'] = not context.existing_open_or_pending_order
    checks['kill_switch_off'] = not context.kill_switch_active
    checks['session_open'] = context.market_session_open
    checks['daily_loss_limit_not_reached'] = context.daily_realized_pnl_cash > -context.max_daily_loss_cash
    effective_daily_pnl = (context.daily_realized_pnl_cash
                           + min(context.daily_unrealized_pnl_cash, 0.0)
                           - context.other_positions_reserved_stress_loss_cash)
    checks['existing_account_downside_within_cap'] = (
        math.isfinite(effective_daily_pnl)
        and effective_daily_pnl > -context.max_daily_loss_cash
    )
    checks['loss_streak_limit_not_reached'] = context.consecutive_losses < context.max_consecutive_losses
    checks['specific_owner_confirmation'] = context.owner_confirmed_this_order
    # Even when all user-declared checks pass, there is NO authenticated feed,
    # atomic ID reservation, durable state or broker connection in this API.
    passed = all(checks.values())
    return {
        'assumption_checks_pass': passed,
        'checks': checks,
        'failed_checks': [key for key, ok in checks.items() if not ok],
        'spread_bps': spread_bps if checks['finite_spread'] else None,
        'effective_daily_pnl_after_existing_risk_cash': (
            effective_daily_pnl if math.isfinite(effective_daily_pnl) else None
        ),
        'quote_authenticated': False,
        'durable_order_reservation': False,
        'durable_circuit_breaker': False,
        'may_execute_paper_order': False,
        'may_execute_real_order': False,
        'warnings': [
            'Inputs are owner-declared and NOT authenticated broker quotes or balances.',
            'Client order IDs and circuit-breaker state are NOT persisted or reserved atomically.',
            'A passing preview is NOT permission to place a demo or real-money order.',
        ],
    }
