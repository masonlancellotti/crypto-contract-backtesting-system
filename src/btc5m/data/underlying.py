"""Underlying BTC market-data clients (Coinbase spot + Binance futures).

Practical first versions using PUBLIC REST endpoints over the standard library
(``urllib``) — a polling fallback that needs no third-party WebSocket dependency
and no credentials. The streaming WS adapters in ``coinbase_ws.py`` /
``binance_futures.py`` remain the future low-latency path.

Endpoints (all public, read-only):
- Coinbase Exchange: /products/BTC-USD/ticker, /trades, /candles
- Binance USDT-M:    /fapi/v1/ticker/bookTicker, /fapi/v1/trades

Each client returns BOTH the raw payload (for ``record_raw``) and a normalized
:class:`~btc5m.schemas.UnderlyingEvent` (for ``record_normalized``).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import AppConfig
from ..schemas import LineSourceStatus, UnderlyingEvent
from ..timeutils import now_ms

_USER_AGENT = "btc5m/0.1 (+research; read-only public endpoints)"


def _http_get_json(url: str, *, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _iso_to_ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        # Coinbase nanosecond precision can exceed datetime's microseconds.
        if "." in s:
            head, tail = s.split(".", 1)
            tzpos = max(tail.find("+"), tail.find("-"))
            frac, tz = (tail[:tzpos], tail[tzpos:]) if tzpos != -1 else (tail, "")
            frac = frac[:6]
            s = f"{head}.{frac}{tz}"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _f(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CoinbaseSpotClient:
    """Public Coinbase Exchange BTC-USD spot client (REST polling)."""

    source = "coinbase"

    def __init__(self, config: AppConfig | None = None, symbol: str = "BTC-USD"):
        self.config = config
        self.symbol = symbol
        src = (config.sources.get("coinbase", {}) if config and config.sources else {})
        self.base_url = src.get("rest_url") or "https://api.exchange.coinbase.com"

    # ----- raw fetches ------------------------------------------------------
    def fetch_ticker_raw(self) -> dict:
        return _http_get_json(f"{self.base_url}/products/{self.symbol}/ticker")

    def fetch_last_trade_raw(self) -> dict:
        rows = _http_get_json(f"{self.base_url}/products/{self.symbol}/trades?limit=1")
        return rows[0] if isinstance(rows, list) and rows else {}

    def fetch_candles_raw(self, start_ms: int, end_ms: int, *, granularity: int = 60) -> list:
        start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"granularity": granularity, "start": start, "end": end}
        url = f"{self.base_url}/products/{self.symbol}/candles?{urllib.parse.urlencode(params)}"
        rows = _http_get_json(url)
        return rows if isinstance(rows, list) else []

    # ----- normalization ----------------------------------------------------
    def normalize_ticker(self, raw: dict) -> UnderlyingEvent:
        bid, ask = _f(raw.get("bid")), _f(raw.get("ask"))
        spread = (ask - bid) if (bid is not None and ask is not None) else None
        return UnderlyingEvent(
            source=self.source,
            symbol=self.symbol,
            event_type="ticker",
            exchange_ts_ms=_iso_to_ms(raw.get("time")),
            recv_ms=now_ms(),
            price=_f(raw.get("price")),
            size=_f(raw.get("size")),
            best_bid=bid,
            best_ask=ask,
            spread=spread,
            raw_ref=str(raw.get("trade_id")) if raw.get("trade_id") is not None else None,
        )

    def normalize_trade(self, raw: dict) -> UnderlyingEvent:
        # Coinbase Exchange trade `side` is the MAKER side; aggressor is the
        # opposite. We report the aggressor (taker) side for flow features.
        maker = raw.get("side")
        aggressor = {"buy": "sell", "sell": "buy"}.get(maker) if maker else None
        return UnderlyingEvent(
            source=self.source,
            symbol=self.symbol,
            event_type="trade",
            exchange_ts_ms=_iso_to_ms(raw.get("time")),
            recv_ms=now_ms(),
            price=_f(raw.get("price")),
            size=_f(raw.get("size")),
            side=aggressor,
            raw_ref=str(raw.get("trade_id")) if raw.get("trade_id") is not None else None,
        )

    # ----- reference price (for line capture) -------------------------------
    def reference_price_now(self) -> tuple[Optional[float], str, dict]:
        """Return (mid-or-last price, source_label, raw_ticker)."""
        raw = self.fetch_ticker_raw()
        ev = self.normalize_ticker(raw)
        price = ev.mid if ev.mid is not None else ev.price
        return price, f"{self.source}:{self.symbol}", raw

    def poll(self) -> list[tuple[dict, UnderlyingEvent]]:
        """One polling cycle: returns [(raw_payload, normalized_event), ...]."""
        out: list[tuple[dict, UnderlyingEvent]] = []
        t = self.fetch_ticker_raw()
        if t:
            out.append((t, self.normalize_ticker(t)))
        tr = self.fetch_last_trade_raw()
        if tr:
            out.append((tr, self.normalize_trade(tr)))
        return out

    def price_at(self, ts_ms: int, *, granularity: int = 60) -> tuple[Optional[float], dict]:
        """Provisional price AT a past timestamp via 1-min candles.

        Uses the OPEN of the candle starting at ``ts_ms`` (price at that minute
        boundary); falls back to the close of the nearest earlier candle.
        Returns (price, detail). Coinbase candles: [time, low, high, open, close, vol].
        """
        rows = self.fetch_candles_raw(ts_ms - 120_000, ts_ms + 120_000, granularity=granularity)
        target = ts_ms // 1000
        target = target - (target % granularity)
        by_time = {int(r[0]): r for r in rows if isinstance(r, list) and len(r) >= 5}
        if target in by_time:
            return _f(by_time[target][3]), {"candle_time": target, "field": "open"}
        # fallback: nearest earlier candle close
        earlier = [t for t in by_time if t <= target]
        if earlier:
            t = max(earlier)
            return _f(by_time[t][4]), {"candle_time": t, "field": "close_fallback"}
        return None, {"reason": "no_candle"}


class BinanceFuturesClient:
    """Public Binance USDT-M futures BTCUSDT client (REST polling)."""

    source = "binance_futures"

    def __init__(self, config: AppConfig | None = None, symbol: str = "BTCUSDT"):
        self.config = config
        self.symbol = symbol
        src = (config.sources.get("binance_futures", {}) if config and config.sources else {})
        self.base_url = src.get("rest_url") or "https://fapi.binance.com"

    def fetch_book_ticker_raw(self) -> dict:
        url = f"{self.base_url}/fapi/v1/ticker/bookTicker?{urllib.parse.urlencode({'symbol': self.symbol})}"
        return _http_get_json(url)

    def fetch_last_trade_raw(self) -> dict:
        url = f"{self.base_url}/fapi/v1/trades?{urllib.parse.urlencode({'symbol': self.symbol, 'limit': 1})}"
        rows = _http_get_json(url)
        return rows[0] if isinstance(rows, list) and rows else {}

    def normalize_book_ticker(self, raw: dict) -> UnderlyingEvent:
        bid, ask = _f(raw.get("bidPrice")), _f(raw.get("askPrice"))
        spread = (ask - bid) if (bid is not None and ask is not None) else None
        return UnderlyingEvent(
            source=self.source,
            symbol=self.symbol,
            event_type="book",
            exchange_ts_ms=int(raw["time"]) if raw.get("time") is not None else None,
            recv_ms=now_ms(),
            best_bid=bid,
            best_ask=ask,
            bid_size=_f(raw.get("bidQty")),
            ask_size=_f(raw.get("askQty")),
            spread=spread,
            raw_ref=str(raw.get("lastUpdateId")) if raw.get("lastUpdateId") is not None else None,
        )

    def normalize_trade(self, raw: dict) -> UnderlyingEvent:
        # isBuyerMaker True => buyer is maker => aggressor is the SELLER.
        is_buyer_maker = raw.get("isBuyerMaker")
        side = None
        if is_buyer_maker is not None:
            side = "sell" if is_buyer_maker else "buy"
        return UnderlyingEvent(
            source=self.source,
            symbol=self.symbol,
            event_type="trade",
            exchange_ts_ms=int(raw["time"]) if raw.get("time") is not None else None,
            recv_ms=now_ms(),
            price=_f(raw.get("price")),
            size=_f(raw.get("qty")),
            side=side,
            raw_ref=str(raw.get("id")) if raw.get("id") is not None else None,
        )

    def reference_price_now(self) -> tuple[Optional[float], str, dict]:
        raw = self.fetch_book_ticker_raw()
        ev = self.normalize_book_ticker(raw)
        return ev.mid, f"{self.source}:{self.symbol}", raw

    def poll(self) -> list[tuple[dict, UnderlyingEvent]]:
        """One polling cycle: returns [(raw_payload, normalized_event), ...]."""
        out: list[tuple[dict, UnderlyingEvent]] = []
        b = self.fetch_book_ticker_raw()
        if b:
            out.append((b, self.normalize_book_ticker(b)))
        tr = self.fetch_last_trade_raw()
        if tr:
            out.append((tr, self.normalize_trade(tr)))
        return out


# Kalshi crypto 15m series -> underlying spot/perp symbols. All five series are
# live on Kalshi (verified 2026-06-10); the pipeline is series-parameterized and
# the underlying feeds follow the series asset.
SERIES_UNDERLYING_SYMBOLS = {
    "KXBTC15M": {"coinbase": "BTC-USD", "binance": "BTCUSDT"},
    "KXETH15M": {"coinbase": "ETH-USD", "binance": "ETHUSDT"},
    "KXSOL15M": {"coinbase": "SOL-USD", "binance": "SOLUSDT"},
    "KXDOGE15M": {"coinbase": "DOGE-USD", "binance": "DOGEUSDT"},
    "KXXRP15M": {"coinbase": "XRP-USD", "binance": "XRPUSDT"},
}


def underlying_symbols_for_series(series: str | None) -> dict:
    """Spot/perp symbols for a Kalshi series (default BTC for unknown/legacy)."""
    return SERIES_UNDERLYING_SYMBOLS.get((series or "").upper(),
                                         SERIES_UNDERLYING_SYMBOLS["KXBTC15M"])


# Registry for CLI --sources resolution.
def build_underlying_client(name: str, config: AppConfig | None = None,
                            series: str | None = None):
    key = name.strip().lower()
    syms = underlying_symbols_for_series(series)
    if key in ("coinbase", "coinbase_spot", "cb"):
        return CoinbaseSpotClient(config, symbol=syms["coinbase"])
    if key in ("binance", "binance_futures", "binance_perp"):
        return BinanceFuturesClient(config, symbol=syms["binance"])
    raise ValueError(f"unknown underlying source: {name!r} (use coinbase|binance)")


__all__ = [
    "CoinbaseSpotClient",
    "BinanceFuturesClient",
    "SERIES_UNDERLYING_SYMBOLS",
    "build_underlying_client",
    "underlying_symbols_for_series",
    "LineSourceStatus",
]
