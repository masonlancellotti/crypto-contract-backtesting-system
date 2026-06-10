"""Executable expected-value labels and realized-PnL labels.

These answer the *correct* question: would buying YES (or NO) at the EXECUTABLE
ask have made money after costs, given the settled outcome? And, given a model
probability, what is the EV of each executable action after costs?

Conventions (Polymarket binary, prices in probability units [0,1]):
- Buying YES at ``yes_ask`` costs ``yes_ask`` per contract; it pays 1 if YES
  resolves (yes_resolved == 1), else 0.
- Buying NO at ``no_ask`` costs ``no_ask``; it pays 1 if YES does NOT resolve
  (yes_resolved == 0), else 0.
- Never assumes midpoint fills; only ask prices are used to enter.

Realized-PnL labels are settlement-grade ONLY if the outcome is OFFICIAL
(``outcome_source_status``). Otherwise they are provisional and flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EvReason(str, Enum):
    OK = "OK"
    MISSING_OUTCOME = "MISSING_OUTCOME"
    MISSING_PRICE = "MISSING_PRICE"
    INVALID_PRICE = "INVALID_PRICE"


def _valid_price(p: Optional[float]) -> bool:
    return p is not None and 0.0 <= p <= 1.0


def binary_trade_pnl(
    side: str, entry_ask: float, yes_resolved: int, *, fee_per_contract: float = 0.0, size: float = 1.0
) -> float:
    """Net realized PnL per executed position after a flat per-contract fee.

    side: "BUY_YES" or "BUY_NO". entry_ask in [0,1]. yes_resolved in {0,1}.
    """
    if side == "BUY_YES":
        payout = 1.0 if yes_resolved == 1 else 0.0
    elif side == "BUY_NO":
        payout = 1.0 if yes_resolved == 0 else 0.0
    else:
        raise ValueError(f"unknown side: {side!r}")
    return (payout - entry_ask) * size - fee_per_contract * size


@dataclass
class ExecutableEvLabels:
    would_buy_yes_at_ask_have_positive_result: Optional[bool]
    would_buy_no_at_ask_have_positive_result: Optional[bool]
    realized_pnl_buy_yes_at_ask: Optional[float]
    realized_pnl_buy_no_at_ask: Optional[float]
    best_executable_side: Optional[str]
    executable_ev_label_after_costs: Optional[float]  # best realized net pnl
    reason_code: str
    label_source_status: str


def executable_ev_labels(
    yes_resolved: Optional[int],
    yes_ask: Optional[float],
    no_ask: Optional[float],
    *,
    fee_per_contract: float = 0.0,
    outcome_source_status: str = "UNKNOWN",
) -> ExecutableEvLabels:
    """Realized executable-EV labels after costs. Explicit reason codes."""
    if yes_resolved not in (0, 1):
        return ExecutableEvLabels(
            None, None, None, None, None, None,
            EvReason.MISSING_OUTCOME.value, outcome_source_status,
        )
    if yes_ask is None and no_ask is None:
        return ExecutableEvLabels(
            None, None, None, None, None, None,
            EvReason.MISSING_PRICE.value, outcome_source_status,
        )

    pnl_yes = pnl_no = None
    pos_yes = pos_no = None
    if yes_ask is not None:
        if not _valid_price(yes_ask):
            return ExecutableEvLabels(None, None, None, None, None, None,
                                      EvReason.INVALID_PRICE.value, outcome_source_status)
        pnl_yes = binary_trade_pnl("BUY_YES", yes_ask, yes_resolved, fee_per_contract=fee_per_contract)
        pos_yes = pnl_yes > 0
    if no_ask is not None:
        if not _valid_price(no_ask):
            return ExecutableEvLabels(None, None, None, None, None, None,
                                      EvReason.INVALID_PRICE.value, outcome_source_status)
        pnl_no = binary_trade_pnl("BUY_NO", no_ask, yes_resolved, fee_per_contract=fee_per_contract)
        pos_no = pnl_no > 0

    candidates = [(s, p) for s, p in (("BUY_YES", pnl_yes), ("BUY_NO", pnl_no)) if p is not None]
    best_side, best_pnl = max(candidates, key=lambda kv: kv[1]) if candidates else (None, None)

    # Realized labels are settlement-grade only if the OUTCOME is official.
    return ExecutableEvLabels(
        would_buy_yes_at_ask_have_positive_result=pos_yes,
        would_buy_no_at_ask_have_positive_result=pos_no,
        realized_pnl_buy_yes_at_ask=pnl_yes,
        realized_pnl_buy_no_at_ask=pnl_no,
        best_executable_side=best_side,
        executable_ev_label_after_costs=best_pnl,
        reason_code=EvReason.OK.value,
        label_source_status=outcome_source_status,
    )


@dataclass
class EvEstimate:
    ev_buy_yes_at_ask: Optional[float]
    ev_buy_no_at_ask: Optional[float]
    best_side: Optional[str]
    best_net_edge: Optional[float]


def expected_value_after_costs(
    p_yes: float,
    yes_ask: Optional[float],
    no_ask: Optional[float],
    *,
    fee_per_contract: float = 0.0,
) -> EvEstimate:
    """Forward-looking EV per contract of each executable action.

    EV(buy YES at ask) = p_yes*1 - yes_ask - fee = p_yes - yes_ask - fee.
    EV(buy NO  at ask) = (1 - p_yes) - no_ask - fee.
    """
    ev_yes = (p_yes - yes_ask - fee_per_contract) if _valid_price(yes_ask) else None
    ev_no = ((1.0 - p_yes) - no_ask - fee_per_contract) if _valid_price(no_ask) else None
    candidates = [(s, e) for s, e in (("BUY_YES", ev_yes), ("BUY_NO", ev_no)) if e is not None]
    best_side, best_edge = max(candidates, key=lambda kv: kv[1]) if candidates else (None, None)
    return EvEstimate(ev_yes, ev_no, best_side, best_edge)
