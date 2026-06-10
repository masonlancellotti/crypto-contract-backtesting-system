"""Coinbase BTC spot WebSocket adapter (scaffold).

Provides a reference BTC-USD spot price stream used as a settlement-relevant
underlying signal. Public market data; no credentials required.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..config import AppConfig
from ..schemas import Quote


class CoinbaseWebSocket:
    def __init__(self, config: AppConfig):
        self.config = config
        src = config.sources.get("coinbase", {})
        self._ws_url = src.get("ws_url") or "wss://ws-feed.exchange.coinbase.com"
        self.product_ids = src.get("product_ids", ["BTC-USD"])

    async def stream(self) -> AsyncIterator[Quote]:
        """Yield BTC-USD quotes. Scaffold: not yet wired."""
        raise NotImplementedError(
            "CoinbaseWebSocket.stream is a scaffold. Implement the ticker/level2 "
            "subscription before use."
        )
        if False:  # pragma: no cover
            yield Quote(source="coinbase", symbol="BTC-USD")
