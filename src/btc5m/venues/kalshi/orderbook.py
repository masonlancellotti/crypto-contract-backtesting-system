"""Kalshi binary orderbook normalization.

Kalshi orderbooks return **bids only**, on both sides:
- ``orderbook_fp.yes_dollars`` = resting YES bids  ``[[price, size], ...]``
- ``orderbook_fp.no_dollars``  = resting NO bids   ``[[price, size], ...]``
Arrays are ASCENDING by price, so the best (highest) bid is the LAST element.
Prices and sizes are strings → parsed with :class:`~decimal.Decimal`.

There are NO explicit asks. To BUY YES you must lift resting NO bids; to BUY NO
you lift resting YES bids. The executable conversions (VERIFIED to match Kalshi's
own published ``yes_ask``/``no_ask``) are::

    yes_ask = 1 - best_no_bid          # cost to BUY 1 YES now
    no_ask  = 1 - best_yes_bid         # cost to BUY 1 NO  now

A NO bid at price ``p`` (size ``s``) is an offer to sell YES at ``1 - p`` for
``s`` contracts; a YES bid at ``p`` (size ``s``) is an offer to sell NO at
``1 - p`` for ``s`` contracts. Depth is walked from the cheapest synthetic ask
upward. No midpoint fills. No invented asks. No infinite depth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

ONE = Decimal("1")
ZERO = Decimal("0")


@dataclass(frozen=True)
class Level:
    """A price level. ``price`` and ``size`` are :class:`Decimal`."""

    price: Decimal
    size: Decimal


def parse_levels(raw_levels) -> list[Level]:
    """Parse ``[[price, size], ...]`` (strings or numbers) into valid Levels.

    Drops malformed entries and out-of-range prices (must be in [0, 1]) and
    non-positive sizes. Never raises on bad input.
    """
    out: list[Level] = []
    for item in raw_levels or []:
        try:
            price = Decimal(str(item[0]))
            size = Decimal(str(item[1]))
        except (InvalidOperation, IndexError, TypeError, ValueError):
            continue
        if price < ZERO or price > ONE or size < ZERO:
            continue
        out.append(Level(price, size))
    return out


def best_bid(levels: list[Level]) -> Optional[Level]:
    """Best (highest-price) bid level, or None for an empty book side."""
    return max(levels, key=lambda lv: lv.price) if levels else None


def asks_from_opposite_bids(opp_bids: list[Level]) -> list[Level]:
    """Convert opposite-side bids into synthetic asks for THIS side.

    Each opposite bid at price ``p`` (size ``s``) becomes an ask at ``1 - p``
    (size ``s``). Returned sorted ASCENDING by ask price (cheapest first), which
    is the order a marketable buy consumes them.
    """
    asks = [Level(ONE - lv.price, lv.size) for lv in opp_bids]
    asks.sort(key=lambda lv: lv.price)
    return asks


def depth_walk(asks_ascending: list[Level], qty: Decimal) -> dict:
    """Walk synthetic asks (cheapest first) to fill ``qty`` contracts.

    Returns avg fill price, filled size, level count consumed, and whether the
    book had enough depth. Never assumes infinite depth — a short book yields a
    partial fill with ``fully_filled=False``.
    """
    if qty is None or qty <= ZERO or not asks_ascending:
        return {"avg_price": None, "filled_size": 0.0, "levels_consumed": 0,
                "fully_filled": False, "requested": float(qty or 0)}
    remaining = qty
    cost = ZERO
    filled = ZERO
    levels = 0
    for lv in asks_ascending:
        if remaining <= ZERO:
            break
        take = lv.size if lv.size < remaining else remaining
        cost += take * lv.price
        filled += take
        remaining -= take
        levels += 1
    avg = (cost / filled) if filled > ZERO else None
    return {
        "avg_price": float(avg) if avg is not None else None,
        "filled_size": float(filled),
        "levels_consumed": levels,
        "fully_filled": remaining <= ZERO,
        "requested": float(qty),
    }


def _extract_sides(raw: dict) -> tuple[list, list]:
    """Pull (yes_bid_raw, no_bid_raw) from either orderbook_fp (dollar strings)
    or the legacy integer-cent ``orderbook`` shape. Cents are scaled to dollars."""
    fp = (raw or {}).get("orderbook_fp")
    if isinstance(fp, dict):
        return fp.get("yes_dollars") or [], fp.get("no_dollars") or []
    ob = (raw or {}).get("orderbook")
    if isinstance(ob, dict):
        def cents(arr):
            out = []
            for it in arr or []:
                try:
                    out.append([str(Decimal(str(it[0])) / Decimal("100")), str(it[1])])
                except (InvalidOperation, IndexError, TypeError, ValueError):
                    continue
            return out
        return cents(ob.get("yes")), cents(ob.get("no"))
    return [], []


def normalize_orderbook(
    raw: dict,
    *,
    market_ticker: str,
    series_ticker: Optional[str] = None,
    event_ticker: Optional[str] = None,
    status: Optional[str] = None,
    window_start_ms: Optional[int] = None,
    close_ms: Optional[int] = None,
    recv_ms: int,
    source_ts_ms: Optional[int] = None,
    fee_status: str = "ASSUMED",
    thin_size: float = 50.0,
    schema_version: int = 1,
) -> dict:
    """Normalize a raw Kalshi orderbook into an executable, venue-tagged event.

    Derives executable YES/NO buy prices from the opposite side's best bid and
    records depth, spreads, and explicit validity flags. Floats are emitted only
    at this storage boundary; all arithmetic above is Decimal.
    """
    yes_raw, no_raw = _extract_sides(raw)
    yes_bids = parse_levels(yes_raw)
    no_bids = parse_levels(no_raw)

    yes_bid_lv = best_bid(yes_bids)
    no_bid_lv = best_bid(no_bids)

    # Executable asks: lift the opposite side's best bid.
    yes_ask = (ONE - no_bid_lv.price) if no_bid_lv else None       # BUY YES
    no_ask = (ONE - yes_bid_lv.price) if yes_bid_lv else None      # BUY NO
    yes_ask_size = no_bid_lv.size if no_bid_lv else None           # size at that ask
    no_ask_size = yes_bid_lv.size if yes_bid_lv else None

    yes_bid = yes_bid_lv.price if yes_bid_lv else None
    no_bid = no_bid_lv.price if no_bid_lv else None

    def _spread(bid, ask):
        return float(ask - bid) if (bid is not None and ask is not None) else None

    def _f(x):
        return float(x) if x is not None else None

    yes_present = yes_bid_lv is not None
    no_present = no_bid_lv is not None
    # crossed/invalid if the synthetic ask is below its own bid (book inconsistency)
    yes_crossed = bool(yes_bid is not None and yes_ask is not None and yes_ask < yes_bid)
    no_crossed = bool(no_bid is not None and no_ask is not None and no_ask < no_bid)
    thin_yes = bool(yes_ask_size is not None and float(yes_ask_size) < thin_size)
    thin_no = bool(no_ask_size is not None and float(no_ask_size) < thin_size)

    flags = {
        "yes_side_present": yes_present,
        "no_side_present": no_present,
        "incomplete_book": not (yes_present and no_present),
        "yes_ask_ge_yes_bid": bool(yes_bid is not None and yes_ask is not None and yes_ask >= yes_bid),
        "no_ask_ge_no_bid": bool(no_bid is not None and no_ask is not None and no_ask >= no_bid),
        "yes_crossed": yes_crossed,
        "no_crossed": no_crossed,
        "thin_yes": thin_yes,
        "thin_no": thin_no,
        "prices_in_range": all(
            ZERO <= v <= ONE for v in (yes_bid, no_bid, yes_ask, no_ask) if v is not None
        ),
    }

    return {
        "venue": "kalshi",
        "schema_version": schema_version,
        "series_ticker": series_ticker,
        "market_ticker": market_ticker,
        "event_ticker": event_ticker,
        "status": status,
        "window_start_ms": window_start_ms,
        "close_ms": close_ms,
        "recv_ms": recv_ms,
        "source_ts_ms": source_ts_ms,
        "quote_age_ms": (recv_ms - source_ts_ms) if source_ts_ms is not None else None,
        "yes_bid": _f(yes_bid),
        "yes_ask": _f(yes_ask),
        "no_bid": _f(no_bid),
        "no_ask": _f(no_ask),
        "yes_bid_size": _f(yes_bid_lv.size) if yes_bid_lv else None,
        "yes_ask_size": _f(yes_ask_size),
        "no_bid_size": _f(no_bid_lv.size) if no_bid_lv else None,
        "no_ask_size": _f(no_ask_size),
        "yes_depth_levels": len(yes_bids),
        "no_depth_levels": len(no_bids),
        "spread_yes": _spread(yes_bid, yes_ask),
        "spread_no": _spread(no_bid, no_ask),
        "mid_yes": (float((yes_bid + yes_ask) / 2) if (yes_bid is not None and yes_ask is not None) else None),
        "executable_yes_buy_price": _f(yes_ask),
        "executable_no_buy_price": _f(no_ask),
        "book_validity_flags": flags,
        "fee_status": fee_status,
        "raw_ref": market_ticker,
    }


def executable_buy(raw: dict, side: str, qty: float) -> dict:
    """Depth-walk an executable BUY for ``side`` ('yes'|'no') and ``qty`` contracts.

    BUY YES walks synthetic YES asks built from NO bids; BUY NO walks synthetic
    NO asks built from YES bids. Returns the depth_walk dict.
    """
    yes_raw, no_raw = _extract_sides(raw)
    if side.lower() == "yes":
        asks = asks_from_opposite_bids(parse_levels(no_raw))
    elif side.lower() == "no":
        asks = asks_from_opposite_bids(parse_levels(yes_raw))
    else:
        raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
    return depth_walk(asks, Decimal(str(qty)))
