"""In-memory Kalshi local order book (snapshot + delta), REST-fallback friendly.

Kalshi books are bids-only on both sides; executable asks are the complement of
the opposite side's best bid (``yes_ask = 1 - best_no_bid``,
``no_ask = 1 - best_yes_bid``) — verified against Kalshi's own asks. This book
keeps per-price bid levels for each side and re-derives the executable view via
:func:`normalize_orderbook` (the single source of truth for asks/depth/validity),
so REST snapshots and (future) WS deltas produce identical normalized output.

Hot-path safe: O(levels) updates, no file I/O, no pandas. WS is optional and
requires auth; when unavailable, feed REST snapshots via :meth:`apply_snapshot`.
"""

from __future__ import annotations

from typing import Optional

from .orderbook import _extract_sides, normalize_orderbook, parse_levels


class KalshiLocalBook:
    """Local executable book for one market ticker."""

    def __init__(
        self,
        *,
        ticker: str,
        series_ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
        status: Optional[str] = None,
        window_start_ms: Optional[int] = None,
        close_ms: Optional[int] = None,
        max_book_age_ms: int = 1000,
        fee_status: str = "ASSUMED",
    ) -> None:
        self.ticker = ticker
        self.series_ticker = series_ticker or (ticker.split("-")[0] if ticker else None)
        self.event_ticker = event_ticker
        self.status = status
        self.window_start_ms = window_start_ms
        self.close_ms = close_ms
        self.max_book_age_ms = max_book_age_ms
        self.fee_status = fee_status
        # price(float) -> size(float) per side (bids only, as Kalshi sends).
        self.yes_bids: dict[float, float] = {}
        self.no_bids: dict[float, float] = {}
        self.recv_ms: Optional[int] = None
        self.source_ts_ms: Optional[int] = None
        self._norm: Optional[dict] = None

    # ----- updates -------------------------------------------------------- #
    def apply_snapshot(self, raw: dict, *, recv_ms: int, source_ts_ms: Optional[int] = None) -> dict:
        """Replace the whole book from a raw Kalshi orderbook payload (REST/WS snapshot)."""
        yes_raw, no_raw = _extract_sides(raw)
        self.yes_bids = {float(lv.price): float(lv.size) for lv in parse_levels(yes_raw)}
        self.no_bids = {float(lv.price): float(lv.size) for lv in parse_levels(no_raw)}
        self.recv_ms = recv_ms
        self.source_ts_ms = source_ts_ms
        return self._rebuild()

    def apply_delta(self, side: str, price: float, size: float, *, recv_ms: int,
                    source_ts_ms: Optional[int] = None) -> dict:
        """Apply a single price-level delta (for WS). size<=0 removes the level."""
        book = self.yes_bids if side.lower() == "yes" else self.no_bids
        p = float(price)
        if size is None or float(size) <= 0:
            book.pop(p, None)
        else:
            book[p] = float(size)
        self.recv_ms = recv_ms
        self.source_ts_ms = source_ts_ms
        return self._rebuild()

    def _rebuild(self) -> dict:
        raw = {"orderbook_fp": {
            "yes_dollars": [[str(p), str(s)] for p, s in self.yes_bids.items()],
            "no_dollars": [[str(p), str(s)] for p, s in self.no_bids.items()],
        }}
        self._norm = normalize_orderbook(
            raw, market_ticker=self.ticker, series_ticker=self.series_ticker,
            event_ticker=self.event_ticker, status=self.status,
            window_start_ms=self.window_start_ms, close_ms=self.close_ms,
            recv_ms=self.recv_ms or 0, source_ts_ms=self.source_ts_ms,
            fee_status=self.fee_status,
        )
        return self._norm

    # ----- reads ---------------------------------------------------------- #
    def normalized(self) -> Optional[dict]:
        return self._norm

    def best_yes_bid(self) -> Optional[float]:
        return self._norm.get("yes_bid") if self._norm else None

    def best_no_bid(self) -> Optional[float]:
        return self._norm.get("no_bid") if self._norm else None

    def yes_ask(self) -> Optional[float]:
        return self._norm.get("yes_ask") if self._norm else None

    def no_ask(self) -> Optional[float]:
        return self._norm.get("no_ask") if self._norm else None

    def top_depth(self) -> float:
        if not self._norm:
            return 0.0
        return (self._norm.get("yes_ask_size") or 0.0) + (self._norm.get("no_ask_size") or 0.0)

    def book_age_ms(self, as_of_ms: int) -> Optional[int]:
        return (as_of_ms - self.recv_ms) if self.recv_ms is not None else None

    def is_stale(self, as_of_ms: int) -> bool:
        age = self.book_age_ms(as_of_ms)
        return age is None or age > self.max_book_age_ms

    def is_valid(self) -> bool:
        if not self._norm:
            return False
        f = self._norm.get("book_validity_flags") or {}
        return bool(not f.get("incomplete_book") and not f.get("yes_crossed")
                    and not f.get("no_crossed") and f.get("prices_in_range", True))
