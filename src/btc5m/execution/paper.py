"""Paper execution adapter.

Simulates fills using the shared, non-midpoint :func:`simulate_fill` (depth-walk
+ fees) and tracks bankroll/positions. Never contacts an exchange. Honors the
risk decision in the context: a blocked decision yields a rejected fill.
"""

from __future__ import annotations

from ..backtest.execution_sim import simulate_fill, to_fill
from ..config import AppConfig
from ..schemas import Fill, Order
from .base import ExecutionAdapter, ExecutionContext


class PaperExecutionAdapter(ExecutionAdapter):
    is_live = False

    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.bankroll = config.paper_starting_bankroll
        self.positions: dict[str, float] = {}
        self.fills: list[Fill] = []

    def submit(self, order: Order, context: ExecutionContext) -> Fill:
        if context.risk_decision is not None and not context.risk_decision.approved:
            return self._reject(
                order,
                "risk blocked: " + "; ".join(context.risk_decision.reasons),
                is_paper=True,
            )
        if not context.levels:
            return self._reject(order, "no liquidity provided to paper adapter", is_paper=True)

        result = simulate_fill(
            order, context.levels, taker_fee_bps=self.config.execution.taker_fee_bps
        )
        fill = to_fill(order, result, is_paper=True)

        if fill.filled_size > 0:
            signed = fill.filled_size if order.side.value == "BUY" else -fill.filled_size
            self.positions[order.contract_id] = self.positions.get(order.contract_id, 0.0) + signed
            cash = fill.filled_size * fill.avg_price + fill.fees
            self.bankroll -= cash if order.side.value == "BUY" else -cash
        self.fills.append(fill)
        return fill
