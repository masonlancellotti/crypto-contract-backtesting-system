"""Execution simulator — walks the book, never assumes midpoint fills.

Shared by the backtester and the paper adapter so simulated and paper fills use
identical, realistic cost assumptions: depth-walking slippage plus explicit
fees. A market taker pays up the book; thin depth produces partial fills.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import BookLevel, Fill, Order, OrderSide


@dataclass
class FillResult:
    filled_size: float
    avg_price: float
    fees: float
    fully_filled: bool


def simulate_fill(
    order: Order,
    levels: list[BookLevel],
    *,
    taker_fee_bps: float = 0.0,
) -> FillResult:
    """Walk `levels` to fill `order`. Levels must be sorted best-first.

    For a BUY, `levels` are the asks (ascending price); for a SELL, the bids
    (descending price). Returns realized average price including slippage, plus
    fees. Never uses the midpoint.
    """
    remaining = order.size
    notional = 0.0
    filled = 0.0
    for lvl in levels:
        if remaining <= 0:
            break
        take = min(remaining, lvl.size)
        notional += take * lvl.price
        filled += take
        remaining -= take

    if filled <= 0:
        return FillResult(filled_size=0.0, avg_price=0.0, fees=0.0, fully_filled=False)

    avg_price = notional / filled
    fees = notional * (taker_fee_bps / 10_000.0)
    return FillResult(
        filled_size=filled,
        avg_price=avg_price,
        fees=fees,
        fully_filled=remaining <= 1e-9,
    )


def to_fill(order: Order, result: FillResult, *, is_paper: bool = True) -> Fill:
    """Wrap a :class:`FillResult` into a :class:`Fill` event."""
    status = "filled" if result.fully_filled else ("partial" if result.filled_size > 0 else "rejected")
    return Fill(
        order=order,
        filled_size=result.filled_size,
        avg_price=result.avg_price,
        fees=result.fees,
        status="simulated" if is_paper else status,
        is_paper=is_paper,
        reason="" if result.filled_size > 0 else "no_liquidity",
    )


def market_levels_for(order: Order, bids: list[BookLevel], asks: list[BookLevel]) -> list[BookLevel]:
    """Select the side of the book a taker order would consume."""
    return asks if order.side == OrderSide.BUY else bids
