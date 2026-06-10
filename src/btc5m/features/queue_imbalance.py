"""Queue / book imbalance features.

Top-of-book imbalance is implemented (stdlib); weighted multi-level imbalance is
a scaffold.
"""

from __future__ import annotations

from typing import Optional

from ..schemas import OrderBook


def top_imbalance(book: OrderBook) -> Optional[float]:
    """Top-of-book imbalance in [-1, 1]: (bid - ask) / (bid + ask) sizes."""
    if not book.best_bid or not book.best_ask:
        return None
    b = book.best_bid.size
    a = book.best_ask.size
    denom = b + a
    if denom <= 0:
        return None
    return (b - a) / denom


def weighted_imbalance(book: OrderBook, levels: int = 5) -> Optional[float]:
    """Depth-weighted imbalance over N levels. Scaffold."""
    raise NotImplementedError("weighted_imbalance is a scaffold.")
