"""Polymarket venue — PARKED / DORMANT.

The Polymarket BTC 5-minute pipeline (discovery, CLOB books, Chainlink line
capture, live CLOB orders) is parked due to account/funding issues. The legacy
implementation still lives under ``btc5m.data`` / ``btc5m.discovery`` /
``btc5m.labels`` and remains runnable MANUALLY, but it is NOT part of the default
pipeline. Kalshi (``btc5m.venues.kalshi``) is the primary venue.

Use :func:`require_polymarket_enabled` to guard any Polymarket entrypoint so it
cannot run by default while dormant.
"""

from __future__ import annotations


class PolymarketDormantError(RuntimeError):
    """Raised when a Polymarket entrypoint is invoked while the venue is dormant."""


def require_polymarket_enabled(config) -> None:
    """Block Polymarket execution unless explicitly re-enabled.

    Set ``POLYMARKET_DORMANT=false`` (or ``polymarket_dormant=False``) to opt in.
    """
    if getattr(config, "polymarket_dormant", True):
        raise PolymarketDormantError(
            "Polymarket is PARKED/DORMANT (account/funding issues). The primary "
            "venue is Kalshi (KXBTC15M). To run the legacy Polymarket path anyway, "
            "set POLYMARKET_DORMANT=false in your environment."
        )
