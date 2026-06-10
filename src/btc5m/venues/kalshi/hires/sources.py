"""High-res config, normalized event builders, and source threads (READ-ONLY).

Sources run as background threads exposing a uniform interface (``latest()`` /
``drain()`` / ``stats()`` / ``request_stop()``). WebSocket sources use the public,
no-auth Coinbase/Binance feeds via the synchronous ``websockets`` client; the Kalshi
source fast-polls the active KXBTC15M book over public REST (Kalshi market-data WS needs
auth and is a scaffold). Every normalized row carries ``recv_ms`` (stamped immediately on
receipt) and ``live_submission_allowed=False``. No orders, no auth, no private endpoints.
"""

from __future__ import annotations

import collections
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ....timeutils import now_ms
from ..client import KalshiClient, iso_to_ms, select_collection_targets
from ..orderbook import normalize_orderbook

COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"
BINANCE_WS_URL = "wss://fstream.binance.com/ws"
WINDOW_MS = 15 * 60 * 1000


# --------------------------------------------------------------------------- #
# Config (env-driven; SAFE defaults — disabled, record-only, no orders)
# --------------------------------------------------------------------------- #
def _b(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _s(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


@dataclass
class HiResConfig:
    enabled: bool = False
    mode: str = "record_only"
    series: str = "KXBTC15M"
    # Kalshi active-book measurement
    kalshi_book_source: str = "rest"            # rest | websocket | auto
    kalshi_rest_poll_ms: int = 500
    kalshi_rest_min_poll_ms: int = 250
    kalshi_max_markets: int = 1
    kalshi_active_only: bool = True
    kalshi_rediscover_ms: int = 1000
    kalshi_backoff_on_error_ms: int = 2000
    # Coinbase / Binance
    coinbase_enabled: bool = True
    coinbase_source: str = "websocket"          # websocket | rest | off
    coinbase_symbol: str = "BTC-USD"
    binance_enabled: bool = True
    binance_source: str = "websocket"
    binance_symbol: str = "BTCUSDT"
    # recording / retention
    record_raw: bool = True
    record_normalized: bool = True
    flush_every_ms: int = 250
    max_runtime_seconds: int = 3600
    output_prefix: str = "hires"
    output_dir: Optional[str] = None            # override base data dir for hires files
    joined: bool = True
    # writer hardening
    writer_mode: str = "threaded"               # sync | threaded
    queue_maxsize: int = 100_000
    queue_warn_size: int = 50_000
    drop_policy: str = "drop_low_priority"      # block | drop_low_priority | drop_oldest_low_priority
    rotate_every_seconds: int = 900
    compress_closed_files: bool = True
    compress_codec: str = "gzip"
    retention_raw_days: int = 7
    retention_normalized_days: int = 30
    retention_joined_days: int = 90
    # Binance high-volume stream controls (aggTrade is heavy -> OFF by default)
    binance_bookticker_enabled: bool = True
    binance_aggtrade_enabled: bool = False
    binance_aggtrade_sample_every_n: int = 1
    binance_max_msgs_per_second: int = 0        # 0 = no cap
    # joined snapshot cadence
    joined_on_kalshi_update: bool = True
    joined_max_hz: int = 5
    # safety (always)
    no_orders: bool = True
    live_submission_allowed: bool = False

    @classmethod
    def from_env(cls) -> "HiResConfig":
        c = cls(
            enabled=_b("KALSHI_HIRES_ENABLED", False),
            mode=_s("KALSHI_HIRES_MODE", "record_only"),
            series=_s("KALSHI_HIRES_SERIES", "KXBTC15M"),
            kalshi_book_source=_s("KALSHI_HIRES_BOOK_SOURCE", "rest"),
            kalshi_rest_poll_ms=_i("KALSHI_HIRES_REST_POLL_MS", 500),
            kalshi_rest_min_poll_ms=_i("KALSHI_HIRES_REST_MIN_POLL_MS", 250),
            kalshi_max_markets=_i("KALSHI_HIRES_MAX_MARKETS", 1),
            kalshi_active_only=_b("KALSHI_HIRES_ACTIVE_ONLY", True),
            kalshi_rediscover_ms=_i("KALSHI_HIRES_REDISCOVER_MS", 1000),
            kalshi_backoff_on_error_ms=_i("KALSHI_HIRES_BACKOFF_ON_ERROR_MS", 2000),
            coinbase_enabled=_b("COINBASE_HIRES_ENABLED", True),
            coinbase_source=_s("COINBASE_HIRES_SOURCE", "websocket"),
            coinbase_symbol=_s("COINBASE_HIRES_SYMBOL", "BTC-USD"),
            binance_enabled=_b("BINANCE_HIRES_ENABLED", True),
            binance_source=_s("BINANCE_HIRES_SOURCE", "websocket"),
            binance_symbol=_s("BINANCE_HIRES_SYMBOL", "BTCUSDT"),
            record_raw=_b("HIRES_RECORD_RAW", True),
            record_normalized=_b("HIRES_RECORD_NORMALIZED", True),
            flush_every_ms=_i("HIRES_FLUSH_EVERY_MS", 250),
            max_runtime_seconds=_i("HIRES_MAX_RUNTIME_SECONDS", 3600),
            output_prefix=_s("HIRES_OUTPUT_PREFIX", "hires"),
            writer_mode=_s("HIRES_WRITER_MODE", "threaded"),
            queue_maxsize=_i("HIRES_QUEUE_MAXSIZE", 100_000),
            queue_warn_size=_i("HIRES_QUEUE_WARN_SIZE", 50_000),
            drop_policy=_s("HIRES_DROP_POLICY", "drop_low_priority"),
            rotate_every_seconds=_i("HIRES_ROTATE_EVERY_SECONDS", 900),
            compress_closed_files=_b("HIRES_COMPRESS_CLOSED_FILES", True),
            compress_codec=_s("HIRES_COMPRESS_CODEC", "gzip"),
            retention_raw_days=_i("HIRES_RETENTION_RAW_DAYS", 7),
            retention_normalized_days=_i("HIRES_RETENTION_NORMALIZED_DAYS", 30),
            retention_joined_days=_i("HIRES_RETENTION_JOINED_DAYS", 90),
            binance_bookticker_enabled=_b("BINANCE_HIRES_BOOKTICKER_ENABLED", True),
            binance_aggtrade_enabled=_b("BINANCE_HIRES_AGGTRADE_ENABLED", False),
            binance_aggtrade_sample_every_n=_i("BINANCE_HIRES_AGGTRADE_SAMPLE_EVERY_N", 1),
            binance_max_msgs_per_second=_i("BINANCE_HIRES_MAX_MSGS_PER_SECOND", 0),
            joined_on_kalshi_update=_b("HIRES_JOINED_ON_KALSHI_UPDATE", True),
            joined_max_hz=_i("HIRES_JOINED_MAX_HZ", 5),
            no_orders=_b("HIRES_NO_ORDERS", True),
            live_submission_allowed=_b("HIRES_LIVE_SUBMISSION_ALLOWED", False),
        )
        # SAFETY: these two can never be flipped on by env in this build.
        c.no_orders = True
        c.live_submission_allowed = False
        return c

    def with_overrides(self, **over) -> "HiResConfig":
        for k, v in over.items():
            if v is not None and hasattr(self, k):
                setattr(self, k, v)
        self.no_orders = True
        self.live_submission_allowed = False
        return self


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    return (bid + ask) / 2.0 if (bid is not None and ask is not None) else None


# --------------------------------------------------------------------------- #
# Normalized event builders (pure functions — unit-testable without network)
# --------------------------------------------------------------------------- #
def coinbase_ticker_event(msg: dict, recv_ms: int) -> dict:
    """Coinbase Exchange `ticker` channel message (carries top-of-book + last trade)."""
    bid, ask = _f(msg.get("best_bid")), _f(msg.get("best_ask"))
    src_ts = iso_to_ms(msg.get("time"))
    return {
        "stream": "hires_coinbase_ticker", "source": "coinbase",
        "symbol": msg.get("product_id") or "BTC-USD", "recv_ms": recv_ms,
        "source_ts_ms": src_ts, "as_of_ms": recv_ms, "seq": msg.get("sequence"),
        "price": _f(msg.get("price")), "best_bid": bid, "best_ask": ask,
        "bid_size": _f(msg.get("best_bid_size")), "ask_size": _f(msg.get("best_ask_size")),
        "mid": _mid(bid, ask), "spread": (ask - bid) if (bid is not None and ask is not None) else None,
        "last_size": _f(msg.get("last_size")), "side": msg.get("side"),
        "data_age_ms": (recv_ms - src_ts) if src_ts is not None else None,
        "raw_ref": str(msg.get("trade_id")) if msg.get("trade_id") is not None else None,
        "live_submission_allowed": False,
    }


def binance_book_ticker_event(msg: dict, recv_ms: int) -> dict:
    """Binance USDT-M `bookTicker` message (b/B/a/A; T transaction time)."""
    bid, ask = _f(msg.get("b")), _f(msg.get("a"))
    src_ts = msg.get("T") or msg.get("E")
    return {
        "stream": "hires_binance_book_ticker", "source": "binance_futures",
        "symbol": msg.get("s") or "BTCUSDT", "recv_ms": recv_ms,
        "source_ts_ms": int(src_ts) if src_ts is not None else None, "as_of_ms": recv_ms,
        "seq": msg.get("u"), "best_bid": bid, "best_ask": ask,
        "bid_size": _f(msg.get("B")), "ask_size": _f(msg.get("A")),
        "mid": _mid(bid, ask), "spread": (ask - bid) if (bid is not None and ask is not None) else None,
        "data_age_ms": (recv_ms - int(src_ts)) if src_ts is not None else None,
        "raw_ref": str(msg.get("u")) if msg.get("u") is not None else None,
        "live_submission_allowed": False,
    }


def binance_trade_event(msg: dict, recv_ms: int) -> dict:
    """Binance USDT-M `aggTrade` message (p/q/m; T trade time)."""
    src_ts = msg.get("T") or msg.get("E")
    return {
        "stream": "hires_binance_trade", "source": "binance_futures",
        "symbol": msg.get("s") or "BTCUSDT", "recv_ms": recv_ms,
        "source_ts_ms": int(src_ts) if src_ts is not None else None, "as_of_ms": recv_ms,
        "seq": msg.get("a"), "price": _f(msg.get("p")), "size": _f(msg.get("q")),
        "side": ("sell" if msg.get("m") else "buy") if msg.get("m") is not None else None,
        "data_age_ms": (recv_ms - int(src_ts)) if src_ts is not None else None,
        "raw_ref": str(msg.get("a")) if msg.get("a") is not None else None,
        "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Base source thread
# --------------------------------------------------------------------------- #
class BaseSource(threading.Thread):
    name: str = "base"
    stream: str = "hires"

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Optional[dict] = None
        self._queue: collections.deque = collections.deque(maxlen=20000)
        self._last_gap_recv: Optional[int] = None
        self._stats = {"messages": 0, "connects": 0, "errors": 0, "drops": 0,
                       "last_recv_ms": None, "last_error": "", "gaps_1s": 0,
                       "gaps_2s": 0, "gaps_5s": 0}

    # ----- lifecycle ----- #
    def request_stop(self) -> None:
        self._stop.set()

    def _sleep(self, ms: float) -> None:
        self._stop.wait(max(0.0, ms) / 1000.0)

    # ----- thread-safe accessors ----- #
    def latest(self) -> Optional[dict]:
        with self._lock:
            return self._latest

    def drain(self) -> list[tuple[Any, dict]]:
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    def stats(self) -> dict:
        with self._lock:
            s = dict(self._stats)
        s["reconnects"] = max(0, s["connects"] - 1)
        return s

    # ----- producer helpers ----- #
    def _emit(self, raw: Any, norm: dict) -> None:
        recv = norm.get("recv_ms")
        with self._lock:
            self._stats["messages"] += 1
            if self._last_gap_recv is not None and recv is not None:
                gap = recv - self._last_gap_recv
                if gap > 5000:
                    self._stats["gaps_5s"] += 1
                elif gap > 2000:
                    self._stats["gaps_2s"] += 1
                elif gap > 1000:
                    self._stats["gaps_1s"] += 1
            self._last_gap_recv = recv
            self._stats["last_recv_ms"] = recv
            self._latest = norm
            if len(self._queue) == self._queue.maxlen:
                self._stats["drops"] += 1
            self._queue.append((raw, norm))

    def _note_connect(self) -> None:
        with self._lock:
            self._stats["connects"] += 1

    def _note_error(self, exc: Exception) -> None:
        with self._lock:
            self._stats["errors"] += 1
            self._stats["last_error"] = f"{type(exc).__name__}: {str(exc)[:140]}"


# --------------------------------------------------------------------------- #
# Coinbase / Binance WebSocket sources (public, no auth)
# --------------------------------------------------------------------------- #
class CoinbaseWSSource(BaseSource):
    name = "coinbase"
    stream = "hires_coinbase_ticker"

    def __init__(self, symbol: str = "BTC-USD", *, url: str = COINBASE_WS_URL,
                 backoff_ms: int = 2000) -> None:
        super().__init__()
        self.symbol = symbol
        self.url = url
        self.backoff_ms = backoff_ms

    def run(self) -> None:
        import json
        from websockets.sync.client import connect
        sub = json.dumps({"type": "subscribe", "product_ids": [self.symbol],
                          "channels": ["ticker"]})
        while not self._stop.is_set():
            try:
                with connect(self.url, open_timeout=10, close_timeout=5, max_queue=256) as ws:
                    ws.send(sub)
                    self._note_connect()
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        recv = now_ms()
                        try:
                            msg = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if msg.get("type") != "ticker":
                            continue
                        self._emit(msg, coinbase_ticker_event(msg, recv))
            except Exception as exc:  # noqa: BLE001 — reconnect on any network error
                if self._stop.is_set():
                    break
                self._note_error(exc)
                self._sleep(self.backoff_ms)


class BinanceWSSource(BaseSource):
    """bookTicker (default) + optional, heavy, sampled/capped aggTrade."""

    name = "binance"
    stream = "hires_binance_book_ticker"

    def __init__(self, symbol: str = "BTCUSDT", *, url: str = BINANCE_WS_URL, backoff_ms: int = 2000,
                 bookticker: bool = True, aggtrade: bool = False, aggtrade_sample_n: int = 1,
                 max_mps: int = 0) -> None:
        super().__init__()
        self.symbol = symbol.lower()
        self.url = url
        self.backoff_ms = backoff_ms
        self.bookticker = bool(bookticker)
        self.aggtrade = bool(aggtrade)
        self.sample_n = max(1, int(aggtrade_sample_n))
        self.max_mps = int(max_mps)
        self._agg_seen = 0
        self._rate_win_s: Optional[int] = None
        self._rate_count = 0
        self._stats.update({"book_msgs": 0, "trade_msgs": 0, "trade_sampled_dropped": 0,
                            "rate_capped": 0})

    def _params(self) -> list[str]:
        p = []
        if self.bookticker:
            p.append(f"{self.symbol}@bookTicker")
        if self.aggtrade:
            p.append(f"{self.symbol}@aggTrade")
        return p

    def _rate_ok(self, recv_ms: int) -> bool:
        if self.max_mps <= 0:
            return True
        sec = recv_ms // 1000
        if sec != self._rate_win_s:
            self._rate_win_s, self._rate_count = sec, 0
        self._rate_count += 1
        if self._rate_count > self.max_mps:
            with self._lock:
                self._stats["rate_capped"] += 1
            return False
        return True

    def _handle_msg(self, msg: dict, recv: int) -> Optional[dict]:
        """Classify a Binance message, apply enable/sample/cap, emit, and return the
        normalized event (or None if filtered). Testable without network."""
        if isinstance(msg, dict) and "stream" in msg and "data" in msg:
            msg = msg["data"]
        if not isinstance(msg, dict):
            return None
        is_book = "b" in msg and "a" in msg
        is_trade = (not is_book) and (msg.get("e") == "aggTrade" or ("p" in msg and "q" in msg))
        if is_trade:
            if not self.aggtrade:
                return None
            self._agg_seen += 1
            if self.sample_n > 1 and (self._agg_seen % self.sample_n) != 0:
                with self._lock:
                    self._stats["trade_sampled_dropped"] += 1
                return None
            if not self._rate_ok(recv):
                return None
            with self._lock:
                self._stats["trade_msgs"] += 1
            ev = binance_trade_event(msg, recv)
            self._emit(msg, ev)
            return ev
        if is_book:
            if not self.bookticker or not self._rate_ok(recv):
                return None
            with self._lock:
                self._stats["book_msgs"] += 1
            ev = binance_book_ticker_event(msg, recv)
            self._emit(msg, ev)
            return ev
        return None

    def run(self) -> None:
        import json
        from websockets.sync.client import connect
        params = self._params()
        if not params:           # nothing enabled -> nothing to do
            return
        sub = json.dumps({"method": "SUBSCRIBE", "params": params, "id": 1})
        while not self._stop.is_set():
            try:
                with connect(self.url, open_timeout=10, close_timeout=5, max_queue=512) as ws:
                    ws.send(sub)
                    self._note_connect()
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        recv = now_ms()
                        try:
                            self._handle_msg(json.loads(raw), recv)
                        except (ValueError, TypeError):
                            continue
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self._note_error(exc)
                self._sleep(self.backoff_ms)


# --------------------------------------------------------------------------- #
# REST polling sources (fallback for CB/Binance; primary for Kalshi)
# --------------------------------------------------------------------------- #
class _RESTPollSource(BaseSource):
    """Generic REST poll loop around an underlying client's ``poll()`` cycle."""

    def __init__(self, client, *, stream_map: dict, poll_ms: int, backoff_ms: int = 2000):
        super().__init__()
        self.client = client
        self.stream_map = stream_map           # event_type -> hires stream name
        self.poll_ms = poll_ms
        self.backoff_ms = backoff_ms

    def run(self) -> None:
        self._note_connect()
        while not self._stop.is_set():
            try:
                for raw, ev in self.client.poll():
                    recv = now_ms()
                    d = ev.__dict__ if hasattr(ev, "__dict__") else dict(ev)
                    etype = d.get("event_type") or "ticker"
                    norm = {
                        "stream": self.stream_map.get(etype, f"hires_{self.name}_{etype}"),
                        "source": d.get("source") or self.name, "symbol": d.get("symbol"),
                        "recv_ms": recv, "source_ts_ms": d.get("exchange_ts_ms"),
                        "as_of_ms": recv, "price": d.get("price"),
                        "best_bid": d.get("best_bid"), "best_ask": d.get("best_ask"),
                        "bid_size": d.get("bid_size"), "ask_size": d.get("ask_size"),
                        "mid": _mid(d.get("best_bid"), d.get("best_ask")), "spread": d.get("spread"),
                        "size": d.get("size"), "side": d.get("side"),
                        "data_age_ms": (recv - d["exchange_ts_ms"]) if d.get("exchange_ts_ms") else None,
                        "raw_ref": d.get("raw_ref"), "live_submission_allowed": False,
                    }
                    self._emit(raw, norm)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self._note_error(exc)
                self._sleep(self.backoff_ms)
                continue
            self._sleep(self.poll_ms)


class CoinbaseRESTSource(_RESTPollSource):
    name = "coinbase"
    stream = "hires_coinbase_ticker"

    def __init__(self, config=None, symbol: str = "BTC-USD", *, poll_ms: int = 500, backoff_ms: int = 2000):
        from ....data.underlying import CoinbaseSpotClient
        super().__init__(CoinbaseSpotClient(config, symbol=symbol),
                         stream_map={"ticker": "hires_coinbase_ticker",
                                     "trade": "hires_coinbase_trade"},
                         poll_ms=poll_ms, backoff_ms=backoff_ms)


class BinanceRESTSource(_RESTPollSource):
    name = "binance"
    stream = "hires_binance_book_ticker"

    def __init__(self, config=None, symbol: str = "BTCUSDT", *, poll_ms: int = 500, backoff_ms: int = 2000):
        from ....data.underlying import BinanceFuturesClient
        super().__init__(BinanceFuturesClient(config, symbol=symbol),
                         stream_map={"book": "hires_binance_book_ticker",
                                     "trade": "hires_binance_trade"},
                         poll_ms=poll_ms, backoff_ms=backoff_ms)


class KalshiRESTBookSource(BaseSource):
    """Fast REST poll of the ACTIVE KXBTC15M book (status-aware; active-first)."""

    name = "kalshi"
    stream = "hires_kalshi_active_book"

    def __init__(self, config, cfg: HiResConfig, *, client=None,
                 line_lookup: Optional[Callable[[str], Optional[float]]] = None):
        super().__init__()
        self.config = config
        self.cfg = cfg
        self.client = client or KalshiClient(config)
        self.series = cfg.series
        self.poll_ms = max(int(cfg.kalshi_rest_poll_ms), int(cfg.kalshi_rest_min_poll_ms))
        self.line_lookup = line_lookup or (lambda _t: None)
        self._active: Optional[dict] = None
        self._last_disc = 0
        self.rate_limited = 0

    def _normalize_book(self, active: dict, raw: dict, recv: int) -> dict:
        """Normalize a raw Kalshi orderbook + hires enrichment. REST has source_ts_ms=null,
        so the age basis is the LOCAL receipt (recv_ms) and the fresh snapshot is NOT stale."""
        tk = active.get("ticker")
        close_ms = iso_to_ms(active.get("close_time"))
        ob = (raw or {}).get("orderbook", raw)
        norm = normalize_orderbook(
            ob if isinstance(ob, dict) else raw, market_ticker=tk, series_ticker=self.series,
            event_ticker=active.get("event_ticker"), status=active.get("status"),
            window_start_ms=(close_ms - WINDOW_MS) if close_ms else None,
            close_ms=close_ms, recv_ms=recv)
        norm["stream"] = "hires_kalshi_active_book"
        norm["as_of_ms"] = recv
        norm["phase"] = active.get("_phase")
        norm["open_ms"] = iso_to_ms(active.get("open_time"))
        norm["seconds_to_close"] = ((close_ms - recv) / 1000.0) if close_ms else None
        norm["reference_start_price"] = self.line_lookup(tk)
        norm["book_age_basis"] = "recv_ms"        # fresh REST snapshot; NOT stale on null source_ts
        norm["book_age_ms"] = 0
        norm["live_submission_allowed"] = False
        return norm

    def _discover_active(self) -> Optional[dict]:
        disc = self.client.discover(series_ticker=self.series, statuses=("open", "unopened"))
        sel = select_collection_targets(disc, max_markets=max(1, int(self.cfg.kalshi_max_markets)))
        if sel["current"]:
            return sel["current"][0]
        if not self.cfg.kalshi_active_only and sel["targets"]:
            return sel["targets"][0]
        return None

    def run(self) -> None:
        import urllib.error
        self._note_connect()
        while not self._stop.is_set():
            try:
                now = now_ms()
                # Discovery is expensive (multi-page REST); the active ticker is stable
                # mid-window. Rediscover only when unknown/expired, near window handoff,
                # or on a slow safety refresh — so the book poll can hit its fast target.
                stc = None
                if self._active is not None:
                    cms = iso_to_ms(self._active.get("close_time"))
                    stc = ((cms - now) / 1000.0) if cms else None
                near_handoff = stc is not None and stc <= 20.0
                expired = stc is not None and stc < 0.0
                refresh_ms = (self.cfg.kalshi_rediscover_ms if near_handoff
                              else max(self.cfg.kalshi_rediscover_ms, 60_000))
                if self._active is None or expired or (now - self._last_disc) >= refresh_ms:
                    self._active = self._discover_active()
                    self._last_disc = now
                if self._active:
                    tk = self._active.get("ticker")
                    raw = self.client.get_orderbook(tk)
                    recv = now_ms()
                    self._emit(raw, self._normalize_book(self._active, raw, recv))
            except urllib.error.HTTPError as exc:  # noqa: PERF203
                if self._stop.is_set():
                    break
                if exc.code == 429:
                    self.rate_limited += 1
                    self._note_error(exc)
                    self._sleep(self.cfg.kalshi_backoff_on_error_ms)
                    continue
                self._note_error(exc)
                self._sleep(self.cfg.kalshi_backoff_on_error_ms)
                continue
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self._note_error(exc)
                self._sleep(self.cfg.kalshi_backoff_on_error_ms)
                continue
            self._sleep(self.poll_ms)


# --------------------------------------------------------------------------- #
# Source factory (used by the real runners; tests inject fakes instead)
# --------------------------------------------------------------------------- #
def websockets_available() -> bool:
    try:
        import websockets.sync.client  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def build_sources(config, cfg: HiResConfig, *, line_lookup=None) -> tuple[list[BaseSource], list[str]]:
    """Instantiate the configured sources. Returns (sources, blockers)."""
    sources: list[BaseSource] = []
    blockers: list[str] = []
    ws_ok = websockets_available()

    def _underlying(name, source, symbol, ws_cls, rest_cls):
        nonlocal blockers
        src = (source or "websocket").lower()
        if src == "off":
            return None
        if src in ("websocket", "auto"):
            if ws_ok:
                return ws_cls(symbol, backoff_ms=cfg.kalshi_backoff_on_error_ms)
            blockers.append(f"{name}: websockets unavailable -> REST fallback")
            return rest_cls(config, symbol, poll_ms=cfg.kalshi_rest_poll_ms,
                            backoff_ms=cfg.kalshi_backoff_on_error_ms)
        return rest_cls(config, symbol, poll_ms=cfg.kalshi_rest_poll_ms,
                        backoff_ms=cfg.kalshi_backoff_on_error_ms)

    if cfg.coinbase_enabled:
        s = _underlying("coinbase", cfg.coinbase_source, cfg.coinbase_symbol,
                        CoinbaseWSSource, CoinbaseRESTSource)
        if s:
            sources.append(s)
    if cfg.binance_enabled:
        src = (cfg.binance_source or "websocket").lower()
        if src != "off":
            if src in ("websocket", "auto") and ws_ok:
                sources.append(BinanceWSSource(
                    cfg.binance_symbol, backoff_ms=cfg.kalshi_backoff_on_error_ms,
                    bookticker=cfg.binance_bookticker_enabled, aggtrade=cfg.binance_aggtrade_enabled,
                    aggtrade_sample_n=cfg.binance_aggtrade_sample_every_n,
                    max_mps=cfg.binance_max_msgs_per_second))
            else:
                if src in ("websocket", "auto"):
                    blockers.append("binance: websockets unavailable -> REST fallback")
                sources.append(BinanceRESTSource(config, cfg.binance_symbol,
                                                 poll_ms=cfg.kalshi_rest_poll_ms,
                                                 backoff_ms=cfg.kalshi_backoff_on_error_ms))
            if cfg.binance_aggtrade_enabled:
                blockers.append(
                    f"binance aggTrade ENABLED (heavy; sample_every_n={cfg.binance_aggtrade_sample_every_n}, "
                    f"max_msgs_per_second={cfg.binance_max_msgs_per_second or 'uncapped'})")
            else:
                blockers.append("binance aggTrade disabled (default; bookTicker only - lighter)")
    # Kalshi book: WS is OPT-IN and auth-gated (READ-ONLY market data); REST is default + fallback.
    if cfg.kalshi_book_source in ("websocket", "auto"):
        from .kalshi_ws import KalshiWSBookSource, ws_book_available
        ok, reason = ws_book_available(config)
        if ok:
            sources.append(KalshiWSBookSource(config, cfg, line_lookup=line_lookup))
            blockers.append("kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)")
        else:
            blockers.append(f"kalshi: WS book unavailable ({reason}) -> REST polling fallback")
            sources.append(KalshiRESTBookSource(config, cfg, line_lookup=line_lookup))
    else:
        sources.append(KalshiRESTBookSource(config, cfg, line_lookup=line_lookup))
    return sources, blockers
