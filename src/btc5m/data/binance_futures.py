"""Binance USDT-M futures WebSocket adapter (scaffold).

Streams BTCUSDT perp/futures book + trade microstructure used for order-flow
and microprice features. Public market data; no credentials required.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..config import AppConfig
from ..schemas import Quote


class BinanceFuturesWebSocket:
    def __init__(self, config: AppConfig):
        self.config = config
        src = config.sources.get("binance_futures", {})
        self._ws_url = src.get("ws_url") or "wss://fstream.binance.com/ws"
        self.symbols = src.get("symbols", ["btcusdt"])

    async def stream(self) -> AsyncIterator[Quote]:
        """Yield BTCUSDT futures quotes. Scaffold: not yet wired."""
        raise NotImplementedError(
            "BinanceFuturesWebSocket.stream is a scaffold. Implement the "
            "bookTicker/depth/aggTrade streams before use."
        )
        if False:  # pragma: no cover
            yield Quote(source="binance_futures", symbol="BTCUSDT")
