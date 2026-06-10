"""Risk manager — the gate every order must pass.

Implements concrete checks for: kill switch, max order size, max position per
contract, max daily loss, max open risk, max trades per hour, stale feeds,
crossed/invalid book, missing settlement metadata, stale model calibration,
clock skew, and feed gaps. Unknown/unset limits are treated conservatively.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from ..config import AppConfig
from ..schemas import ContractMeta, Order, OrderBook, RiskDecision
from ..timeutils import age_ms, now_ms


@dataclass
class RiskContext:
    """Live state the risk manager evaluates an order against."""

    book: Optional[OrderBook] = None
    meta: Optional[ContractMeta] = None
    calibration_ts_ms: Optional[int] = None   # when current model was calibrated
    clock_skew_ms: int = 0
    last_feed_event_ms: Optional[int] = None   # for feed-gap detection
    ref_ms: Optional[int] = None


@dataclass
class RiskState:
    """Mutable session risk accounting."""

    daily_loss: float = 0.0
    open_risk: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)  # contract_id -> net size
    trade_times_ms: deque[int] = field(default_factory=deque)


class RiskManager:
    def __init__(self, config: AppConfig, state: RiskState | None = None):
        self.config = config
        self.state = state or RiskState()

    # ----- Main entry -------------------------------------------------------
    def evaluate(self, order: Order, ctx: RiskContext | None = None) -> RiskDecision:
        """Return a :class:`RiskDecision`. Approved only if ALL checks pass."""
        ctx = ctx or RiskContext()
        ref = ctx.ref_ms if ctx.ref_ms is not None else now_ms()
        r = self.config.risk
        reasons: list[str] = []

        # 1. Kill switch
        if self.config.kill_switch_enabled:
            reasons.append("kill switch active (KILL_SWITCH_ENABLED=true)")

        # 2. Max order size
        if r.max_order_size is None:
            reasons.append("max_order_size not set")
        elif order.size > r.max_order_size:
            reasons.append(f"order size {order.size} > max_order_size {r.max_order_size}")

        # 3. Max position per contract (post-trade projection)
        signed = order.size if order.side.value == "BUY" else -order.size
        projected = self.state.positions.get(order.contract_id, 0.0) + signed
        if r.max_position_per_contract is None:
            reasons.append("max_position_per_contract not set")
        elif abs(projected) > r.max_position_per_contract:
            reasons.append(
                f"projected position {projected} exceeds max_position_per_contract "
                f"{r.max_position_per_contract}"
            )

        # 4. Max daily loss
        if r.max_daily_loss is None:
            reasons.append("max_daily_loss not set")
        elif self.state.daily_loss >= r.max_daily_loss:
            reasons.append(f"daily loss {self.state.daily_loss} >= max_daily_loss {r.max_daily_loss}")

        # 5. Max open risk (approx incremental notional)
        incremental = order.size * order.price
        if r.max_open_risk is None:
            reasons.append("max_open_risk not set")
        elif self.state.open_risk + incremental > r.max_open_risk:
            reasons.append("projected open risk exceeds max_open_risk")

        # 6. Max trades per hour
        if r.max_trades_per_hour is None:
            reasons.append("max_trades_per_hour not set")
        else:
            cutoff = ref - 3_600_000
            recent = sum(1 for t in self.state.trade_times_ms if t >= cutoff)
            if recent >= r.max_trades_per_hour:
                reasons.append(f"trades in last hour {recent} >= max_trades_per_hour")

        # 7. Stale feed / quote age
        if ctx.book is not None:
            qage = age_ms(ctx.book.ts_ms, ref_ms=ref)
            if qage > r.max_quote_age_ms:
                reasons.append(f"stale quote: age {qage}ms > max_quote_age_ms {r.max_quote_age_ms}")
            # 8. Crossed / invalid book
            if r.reject_crossed_book and ctx.book.is_crossed:
                reasons.append("crossed/invalid Polymarket book")
            if ctx.book.best_bid is None or ctx.book.best_ask is None:
                reasons.append("incomplete book (missing a side)")

        # 9. Missing settlement metadata
        if r.require_settlement_metadata:
            if ctx.meta is None or not ctx.meta.has_settlement_metadata:
                reasons.append("missing/incomplete settlement metadata")

        # 10. Stale model calibration
        if ctx.calibration_ts_ms is None:
            reasons.append("model calibration timestamp missing (uncalibrated)")
        else:
            cal_age_h = age_ms(ctx.calibration_ts_ms, ref_ms=ref) / 3_600_000
            if cal_age_h > r.max_calibration_age_hours:
                reasons.append(
                    f"stale calibration: {cal_age_h:.1f}h > max {r.max_calibration_age_hours}h"
                )

        # 11. Clock skew
        if abs(ctx.clock_skew_ms) > r.max_clock_skew_ms:
            reasons.append(f"clock skew {ctx.clock_skew_ms}ms > max {r.max_clock_skew_ms}ms")

        # 12. Feed gap / reconnect
        if ctx.last_feed_event_ms is not None:
            gap = age_ms(ctx.last_feed_event_ms, ref_ms=ref)
            if gap > r.max_feed_gap_ms:
                reasons.append(f"feed gap {gap}ms > max_feed_gap_ms {r.max_feed_gap_ms}")

        return RiskDecision.ok() if not reasons else RiskDecision.blocked(*reasons)

    # ----- Accounting -------------------------------------------------------
    def record_trade(self, order: Order, *, ts_ms: int | None = None) -> None:
        """Update session state after an accepted trade."""
        t = ts_ms if ts_ms is not None else now_ms()
        self.state.trade_times_ms.append(t)
        signed = order.size if order.side.value == "BUY" else -order.size
        self.state.positions[order.contract_id] = (
            self.state.positions.get(order.contract_id, 0.0) + signed
        )
        self.state.open_risk += order.size * order.price
