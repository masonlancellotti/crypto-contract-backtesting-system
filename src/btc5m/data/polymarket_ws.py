"""Polymarket order-book WebSocket stream (scaffold).

Streams book/quote updates for subscribed token ids on the CLOB **market**
channel and yields normalized :class:`OrderBook` snapshots, tracking source vs
receive timestamps so staleness/latency gates have real values.

Status: the live WS path requires the optional ``websockets`` dependency and is
NOT yet wired (``stream`` raises). For real recording today, the CLI ``record``
command polls the public CLOB REST ``/book`` endpoint via
:class:`~btc5m.data.polymarket_client.PolymarketClient` (stdlib only, no creds).
The subscription payload below documents the exact market-channel message so the
WS path can be completed without guesswork.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Iterable

from ..config import AppConfig
from ..schemas import OrderBook

# CLOB market channel subscribe message (documented format).
# Connect to wss://ws-subscriptions-clob.polymarket.com/ws/market then send:
#   {"assets_ids": ["<token_id>", ...], "type": "market"}
# Server emits "book" (full snapshot) and "price_change" (deltas) events.


class PolymarketWebSocket:
    """WebSocket client for the Polymarket CLOB market channel (scaffold)."""

    def __init__(self, config: AppConfig, token_ids: Iterable[str] | None = None):
        self.config = config
        self.token_ids = list(token_ids or [])
        src = config.sources.get("polymarket", {}) if config.sources else {}
        self._ws_url = (
            src.get("ws_url") or "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        )

    def subscribe_message(self) -> str:
        """Return the JSON subscribe payload for the configured token ids."""
        return json.dumps({"assets_ids": self.token_ids, "type": "market"})

    async def stream(self) -> AsyncIterator[OrderBook]:
        """Yield normalized order-book snapshots. Scaffold: not yet wired."""
        raise NotImplementedError(
            "PolymarketWebSocket.stream is a scaffold. Implement the CLOB market "
            "channel using the optional `websockets` dependency and "
            "subscribe_message(); until then use the REST-polling `record` CLI."
        )
        if False:  # pragma: no cover - keeps this an async generator for typing
            yield OrderBook(contract_id="", outcome=None)  # type: ignore

    def _connect(self):
        import websockets  # noqa: F401 (lazy import; optional dependency)

        return None
