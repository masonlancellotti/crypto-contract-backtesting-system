"""Execution adapter interface.

All adapters implement :meth:`ExecutionAdapter.submit`, which takes an
:class:`Order` plus an :class:`ExecutionContext` (the current book side to fill
against and a pre-computed risk decision) and returns a :class:`Fill`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from ..config import AppConfig
from ..schemas import BookLevel, Fill, Order, RiskDecision


@dataclass
class ExecutionContext:
    """Inputs an adapter needs to (simulate or submit) a fill realistically."""

    # Levels the taker order would consume (asks for BUY, bids for SELL),
    # sorted best-first. Used for non-midpoint, depth-walking fills.
    levels: list[BookLevel] = field(default_factory=list)
    risk_decision: RiskDecision | None = None


class ExecutionAdapter(abc.ABC):
    """Base class for paper and live execution adapters."""

    is_live: bool = False

    def __init__(self, config: AppConfig):
        self.config = config

    @abc.abstractmethod
    def submit(self, order: Order, context: ExecutionContext) -> Fill:
        """Submit (or simulate) an order and return the resulting fill."""

    def _reject(self, order: Order, reason: str, *, is_paper: bool) -> Fill:
        return Fill(
            order=order,
            filled_size=0.0,
            avg_price=0.0,
            fees=0.0,
            status="rejected",
            is_paper=is_paper,
            reason=reason,
        )
