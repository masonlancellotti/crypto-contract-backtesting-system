"""Microprice features.

Stoikov microprice (size-weighted fair price) is implemented at the top level
(stdlib). This is a fair-value estimate, NOT an assumed fill price.
"""

from __future__ import annotations

from typing import Optional

from ..schemas import OrderBook


def microprice(book: OrderBook) -> Optional[float]:
    """Size-weighted microprice. Diagnostic fair value, not a fill assumption."""
    if not book.best_bid or not book.best_ask:
        return None
    pb, sb = book.best_bid.price, book.best_bid.size
    pa, sa = book.best_ask.price, book.best_ask.size
    denom = sb + sa
    if denom <= 0:
        return book.mid
    # Heavier near-side weight pulls the fair price toward the thicker side.
    return (pb * sa + pa * sb) / denom
