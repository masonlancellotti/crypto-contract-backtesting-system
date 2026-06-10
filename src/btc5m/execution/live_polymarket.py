"""Live Polymarket execution adapter (GATED SCAFFOLD).

This adapter EXISTS but refuses to submit any order unless ALL gates pass:

    1. TRADING_MODE = live
    2. LIVE_TRADING_ENABLED = true
    3. kill switch permits trading (KILL_SWITCH_ENABLED = false)
    4. required Polymarket credentials are present
    5. risk checks pass (the provided RiskDecision is approved)
    6. manual confirmation satisfied if REQUIRE_MANUAL_CONFIRMATION = true

With shipped defaults, every submit returns a rejected fill explaining why. The
real order-placement path is intentionally left unimplemented.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..config import AppConfig
from ..schemas import Fill, Order
from .base import ExecutionAdapter, ExecutionContext


class LivePolymarketExecutionAdapter(ExecutionAdapter):
    is_live = True

    def __init__(self, config: AppConfig, confirm_fn: Optional[Callable[[Order], bool]] = None):
        super().__init__(config)
        # Optional callback to satisfy manual confirmation. If None and manual
        # confirmation is required, the adapter refuses (safe default).
        self._confirm_fn = confirm_fn

    def preflight(self, order: Order, context: ExecutionContext) -> list[str]:
        """Return the list of blockers preventing a live order. Empty == clear."""
        blockers = list(self.config.live_blockers())  # mode/enable/killswitch/creds/limits

        if context.risk_decision is None:
            blockers.append("no risk decision provided")
        elif not context.risk_decision.approved:
            blockers.extend(f"risk: {r}" for r in context.risk_decision.reasons)

        if self.config.require_manual_confirmation:
            if self._confirm_fn is None:
                blockers.append("manual confirmation required but no confirmation handler set")
            elif not self._confirm_fn(order):
                blockers.append("manual confirmation not granted")

        return blockers

    def submit(self, order: Order, context: ExecutionContext) -> Fill:
        blockers = self.preflight(order, context)
        if blockers:
            return self._reject(order, "LIVE REFUSED: " + "; ".join(blockers), is_paper=False)

        # All gates passed. The actual CLOB order placement is intentionally NOT
        # implemented in this bootstrap. Refuse rather than silently no-op.
        raise NotImplementedError(
            "Live order placement is not implemented in this bootstrap. All safety "
            "gates passed, but real submission must be implemented and reviewed "
            "deliberately before any live order is sent."
        )
