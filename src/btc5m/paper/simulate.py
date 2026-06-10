"""Non-midpoint paper fill simulation for Polymarket binary contracts.

A taker BUY consumes the ASK ladder of the chosen outcome token; a SELL consumes
the BID ladder. Fills depth-walk the visible ladder and charge fees — the
midpoint is NEVER used. Settlement PnL uses the realized average fill price.

Reuses :func:`btc5m.backtest.execution_sim.simulate_fill` so paper and backtest
fills share identical, realistic cost assumptions.
"""

from __future__ import annotations

from typing import Optional

from ..backtest.execution_sim import simulate_fill, to_fill
from ..schemas import BookLevel, Fill, Order, OrderSide, Outcome


def _levels_from_event(event: Optional[dict], side_key: str) -> list[BookLevel]:
    """Build a BookLevel ladder from a normalized book event's bids/asks list."""
    if not event:
        return []
    raw = event.get(side_key) or []
    out: list[BookLevel] = []
    for lvl in raw:
        try:
            price, size = float(lvl[0]), float(lvl[1])
        except (TypeError, ValueError, IndexError):
            continue
        if size > 0:
            out.append(BookLevel(price, size))
    return out


def executable_levels(decision_side: str, yes_event: Optional[dict], no_event: Optional[dict]):
    """Return (outcome, ladder) a taker BUY would consume for a decision side.

    BUY_YES -> walk the YES ask ladder; BUY_NO -> walk the NO ask ladder.
    """
    if decision_side == "BUY_YES":
        return Outcome.YES, _levels_from_event(yes_event, "asks")
    if decision_side == "BUY_NO":
        return Outcome.NO, _levels_from_event(no_event, "asks")
    return None, []


def simulate_paper_fill(
    decision_side: str,
    yes_event: Optional[dict],
    no_event: Optional[dict],
    *,
    contract_id: str = "",
    requested_size: float = 10.0,
    taker_fee_bps: float = 0.0,
    ref_price: Optional[float] = None,
) -> Fill:
    """Simulate a taker BUY at the ask ladder (depth-walk, fees, no midpoint)."""
    outcome, levels = executable_levels(decision_side, yes_event, no_event)
    order = Order(
        contract_id=contract_id,
        outcome=outcome or Outcome.YES,
        side=OrderSide.BUY,
        price=(ref_price if ref_price is not None else (levels[0].price if levels else 0.0)),
        size=requested_size,
        client_order_id="paper",
    )
    if not levels:
        return Fill(order=order, filled_size=0.0, avg_price=0.0, fees=0.0,
                    status="rejected", is_paper=True, reason="no_ask_liquidity")
    result = simulate_fill(order, levels, taker_fee_bps=taker_fee_bps)
    return to_fill(order, result, is_paper=True)


def realized_binary_pnl(
    decision_side: str, fill: Fill, yes_resolved: Optional[int]
) -> Optional[float]:
    """Net PnL of a settled paper position. None if outcome unknown / no fill.

    BUY_YES pays 1 if yes_resolved==1; BUY_NO pays 1 if yes_resolved==0. PnL is
    (payout - avg_fill_price) * filled_size - fees. Uses the realized fill price,
    never the midpoint.
    """
    if yes_resolved not in (0, 1) or fill.filled_size <= 0:
        return None
    if decision_side == "BUY_YES":
        payout = 1.0 if yes_resolved == 1 else 0.0
    elif decision_side == "BUY_NO":
        payout = 1.0 if yes_resolved == 0 else 0.0
    else:
        return None
    return (payout - fill.avg_price) * fill.filled_size - fill.fees
