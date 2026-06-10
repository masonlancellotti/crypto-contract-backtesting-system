"""Kalshi authenticated WebSocket client — SCAFFOLD (REST fallback otherwise).

Kalshi's market-data WebSocket requires RSA-signed authentication
(``KALSHI_KEY_ID`` + ``KALSHI_PRIVATE_KEY_PATH``) and the ``websockets`` library.
This module is an honest scaffold: it reports whether WS is *available* and, if
not, the precise blocker — it NEVER raises into the caller's hot path. Callers
check :meth:`availability` and fall back to REST polling in paper/read-only mode.

No order submission. No secrets printed. No private-key content ever read here.
"""

from __future__ import annotations

from typing import Any


class KalshiWSClient:
    """Availability probe + connect stub for the (future) Kalshi market WS."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.ws_url = getattr(getattr(config, "kalshi", None), "ws_url", "") or ""

    def availability(self) -> dict:
        """Return ``{available, reason}`` — always safe, never raises.

        ``available`` is False in this build (WS streaming is not implemented);
        the reason distinguishes "disabled", "no URL", "no auth", and "scaffold"
        so the runtime can log the right fallback message.
        """
        ll = getattr(self.config, "low_latency", None)
        use_ws = bool(getattr(ll, "use_websocket", False))
        auth = bool(getattr(getattr(self.config, "kalshi", None), "auth_configured", False))
        if not use_ws:
            return {"available": False, "reason": "KALSHI_USE_WEBSOCKET=false; using REST fallback"}
        if not self.ws_url:
            return {"available": False, "reason": "no KALSHI_WS_URL configured; using REST fallback"}
        if not auth:
            return {"available": False,
                    "reason": "Kalshi WS requires auth (KALSHI_KEY_ID + KALSHI_PRIVATE_KEY_PATH); "
                              "none set — using REST fallback (paper/read-only)"}
        return {"available": False,
                "reason": "Kalshi WS streaming not implemented in this build (scaffold); using REST fallback"}

    def connect(self):  # pragma: no cover - scaffold
        raise NotImplementedError(
            "KalshiWSClient.connect is a scaffold. Implement RSA-signed auth + the "
            "market data subscription, or use the REST polling fallback. No orders.")
