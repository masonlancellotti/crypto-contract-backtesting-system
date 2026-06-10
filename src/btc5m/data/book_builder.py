"""Local order-book builder.

Maintains a normalized :class:`OrderBook` per contract/outcome from incremental
or snapshot updates. Functional (stdlib only) so it can be unit-tested without
live feeds. Flags crossed/invalid books rather than silently fixing them.
"""

from __future__ import annotations

from ..schemas import BookLevel, OrderBook, Outcome
from ..timeutils import now_ms


class BookBuilder:
    """Builds and maintains normalized books keyed by (contract_id, outcome)."""

    def __init__(self) -> None:
        self._books: dict[tuple[str, Outcome], OrderBook] = {}

    def apply_snapshot(
        self,
        contract_id: str,
        outcome: Outcome,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        *,
        ts_ms: int | None = None,
        recv_ms: int | None = None,
    ) -> OrderBook:
        """Replace the book for a contract/outcome from a full snapshot."""
        recv = recv_ms if recv_ms is not None else now_ms()
        book = OrderBook(
            contract_id=contract_id,
            outcome=outcome,
            bids=sorted(
                (BookLevel(p, s) for p, s in bids if s > 0), key=lambda x: -x.price
            ),
            asks=sorted(
                (BookLevel(p, s) for p, s in asks if s > 0), key=lambda x: x.price
            ),
            ts_ms=ts_ms if ts_ms is not None else recv,
            recv_ms=recv,
        )
        self._books[(contract_id, outcome)] = book
        return book

    def get(self, contract_id: str, outcome: Outcome) -> OrderBook | None:
        return self._books.get((contract_id, outcome))

    @staticmethod
    def is_valid(book: OrderBook) -> bool:
        """A book is valid if it has both sides and is not crossed."""
        return (
            book.best_bid is not None
            and book.best_ask is not None
            and not book.is_crossed
        )
