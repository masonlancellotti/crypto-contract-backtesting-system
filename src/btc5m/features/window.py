"""Point-in-time underlying microstructure aggregation (no lookahead).

An :class:`UnderlyingWindow` ingests normalized BTC events (Coinbase spot /
Binance futures) in time order and derives features **as of** a timestamp using
ONLY events at or before that timestamp. Every method that produces features
takes ``as_of_ms`` and filters strictly, so there is no look-ahead.

Features: short-horizon log returns, realized volatility, cumulative volume
delta (CVD), trade intensity, level-1 order-flow imbalance (OFI) from book
ticks, spread, microprice divergence, and feed-staleness fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_HORIZONS_S = (1, 3, 5, 10, 15, 30, 60, 180)


@dataclass
class _PricePoint:
    ts_ms: int
    price: float


@dataclass
class _Trade:
    ts_ms: int
    price: float
    signed_size: float  # +size if aggressor buy, -size if sell, 0 if unknown


@dataclass
class _BookTick:
    ts_ms: int
    best_bid: Optional[float]
    best_ask: Optional[float]
    bid_size: Optional[float]
    ask_size: Optional[float]


@dataclass
class UnderlyingWindow:
    """Accumulates one source's events; computes point-in-time features."""

    source: str = "underlying"
    prices: list[_PricePoint] = field(default_factory=list)
    trades: list[_Trade] = field(default_factory=list)
    book_ticks: list[_BookTick] = field(default_factory=list)

    # ----- ingestion --------------------------------------------------------
    def add_event(self, ev: dict) -> None:
        """Ingest a normalized UnderlyingEvent dict (uses exchange ts, else recv)."""
        ts = ev.get("exchange_ts_ms") or ev.get("recv_ms")
        if ts is None:
            return
        ts = int(ts)
        etype = ev.get("event_type")
        price = ev.get("price")
        mid = None
        bb, ba = ev.get("best_bid"), ev.get("best_ask")
        if bb is not None and ba is not None:
            mid = (bb + ba) / 2.0
        ref = mid if mid is not None else price
        if ref is not None:
            self.prices.append(_PricePoint(ts, float(ref)))
        if etype == "trade" and price is not None:
            size = ev.get("size") or 0.0
            side = ev.get("side")
            signed = float(size) if side == "buy" else (-float(size) if side == "sell" else 0.0)
            self.trades.append(_Trade(ts, float(price), signed))
        if etype in ("book", "ticker") and (bb is not None or ba is not None):
            self.book_ticks.append(_BookTick(ts, bb, ba, ev.get("bid_size"), ev.get("ask_size")))

    # ----- helpers (no lookahead: everything filters ts <= as_of_ms) --------
    def _price_at_or_before(self, ts_ms: int) -> Optional[float]:
        chosen = None
        for p in self.prices:
            if p.ts_ms <= ts_ms:
                chosen = p.price
            else:
                break
        return chosen

    def last_price(self, as_of_ms: int) -> Optional[float]:
        return self._price_at_or_before(as_of_ms)

    def _prices_between(self, lo_ms: int, hi_ms: int) -> list[float]:
        return [p.price for p in self.prices if lo_ms < p.ts_ms <= hi_ms]

    # ----- feature blocks ---------------------------------------------------
    def returns(self, as_of_ms: int, horizons_s=DEFAULT_HORIZONS_S) -> dict:
        out: dict[str, Optional[float]] = {}
        p_now = self._price_at_or_before(as_of_ms)
        for h in horizons_s:
            p_then = self._price_at_or_before(as_of_ms - h * 1000)
            if p_now and p_then and p_then > 0:
                out[f"ret_{h}s"] = math.log(p_now / p_then)
            else:
                out[f"ret_{h}s"] = None
        return out

    def realized_vol(self, as_of_ms: int, horizons_s=(10, 30, 60, 180)) -> dict:
        out: dict[str, Optional[float]] = {}
        for h in horizons_s:
            series = self._prices_between(as_of_ms - h * 1000, as_of_ms)
            if len(series) >= 3:
                rets = [
                    math.log(series[i] / series[i - 1])
                    for i in range(1, len(series))
                    if series[i - 1] > 0
                ]
                if len(rets) >= 2:
                    mean = sum(rets) / len(rets)
                    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
                    out[f"rv_{h}s"] = math.sqrt(var)
                    continue
            out[f"rv_{h}s"] = None
        return out

    def flow(self, as_of_ms: int, horizons_s=(5, 30, 60)) -> dict:
        out: dict[str, Optional[float]] = {}
        # Cumulative volume delta over the whole window up to as_of.
        cvd = sum(t.signed_size for t in self.trades if t.ts_ms <= as_of_ms)
        out["cvd_cumulative"] = cvd
        for h in horizons_s:
            lo = as_of_ms - h * 1000
            window = [t for t in self.trades if lo < t.ts_ms <= as_of_ms]
            out[f"cvd_{h}s"] = sum(t.signed_size for t in window)
            out[f"trade_intensity_{h}s"] = float(len(window))
            buys = sum(t.signed_size for t in window if t.signed_size > 0)
            sells = -sum(t.signed_size for t in window if t.signed_size < 0)
            denom = buys + sells
            out[f"trade_imbalance_{h}s"] = (buys - sells) / denom if denom > 0 else None
        return out

    def ofi_l1(self, as_of_ms: int, horizon_s: int = 30) -> Optional[float]:
        """Level-1 order-flow imbalance summed over recent book ticks."""
        lo = as_of_ms - horizon_s * 1000
        ticks = [t for t in self.book_ticks if lo < t.ts_ms <= as_of_ms]
        total = 0.0
        prev: Optional[_BookTick] = None
        for t in ticks:
            if (
                prev is not None
                and None not in (t.best_bid, t.best_ask, t.bid_size, t.ask_size,
                                 prev.best_bid, prev.best_ask, prev.bid_size, prev.ask_size)
            ):
                d_bid = (
                    t.bid_size if t.best_bid > prev.best_bid
                    else (t.bid_size - prev.bid_size if t.best_bid == prev.best_bid else -prev.bid_size)
                )
                d_ask = (
                    t.ask_size if t.best_ask < prev.best_ask
                    else (t.ask_size - prev.ask_size if t.best_ask == prev.best_ask else -prev.ask_size)
                )
                total += d_bid - d_ask
            prev = t
        return total if ticks else None

    def book_state(self, as_of_ms: int) -> dict:
        """Latest book tick state + microprice divergence, as of as_of_ms."""
        latest = None
        for t in self.book_ticks:
            if t.ts_ms <= as_of_ms:
                latest = t
            else:
                break
        if latest is None or latest.best_bid is None or latest.best_ask is None:
            return {"u_spread": None, "u_microprice_minus_mid": None, "u_book_imbalance": None}
        mid = (latest.best_bid + latest.best_ask) / 2.0
        bs, as_ = latest.bid_size, latest.ask_size
        micro_div = None
        imb = None
        if bs is not None and as_ is not None and (bs + as_) > 0:
            microprice = (latest.best_bid * as_ + latest.best_ask * bs) / (bs + as_)
            micro_div = microprice - mid
            imb = (bs - as_) / (bs + as_)
        return {
            "u_spread": latest.best_ask - latest.best_bid,
            "u_microprice_minus_mid": micro_div,
            "u_book_imbalance": imb,
        }

    def staleness(self, as_of_ms: int) -> dict:
        last_trade = max((t.ts_ms for t in self.trades if t.ts_ms <= as_of_ms), default=None)
        last_book = max((t.ts_ms for t in self.book_ticks if t.ts_ms <= as_of_ms), default=None)
        last_any = max((p.ts_ms for p in self.prices if p.ts_ms <= as_of_ms), default=None)
        return {
            "u_ms_since_last_trade": (as_of_ms - last_trade) if last_trade is not None else None,
            "u_ms_since_last_book": (as_of_ms - last_book) if last_book is not None else None,
            "u_ms_since_last_event": (as_of_ms - last_any) if last_any is not None else None,
            "u_event_count": sum(1 for p in self.prices if p.ts_ms <= as_of_ms),
        }

    def features(self, as_of_ms: int, *, prefix: str = "") -> dict:
        """All underlying features as of as_of_ms. Prefix disambiguates sources."""
        out: dict = {}
        out.update(self.returns(as_of_ms))
        out.update(self.realized_vol(as_of_ms))
        out.update(self.flow(as_of_ms))
        out["ofi_l1_30s"] = self.ofi_l1(as_of_ms, 30)
        out.update(self.book_state(as_of_ms))
        out.update(self.staleness(as_of_ms))
        out["last_price"] = self.last_price(as_of_ms)
        if prefix:
            out = {f"{prefix}{k}": v for k, v in out.items()}
        return out
