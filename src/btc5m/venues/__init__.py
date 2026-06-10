"""Venue adapters.

PRIMARY venue: ``kalshi`` (Kalshi BTC 15-minute Up/Down, series KXBTC15M).
DORMANT venue: ``polymarket`` — parked reference implementation; not part of the
default pipeline. Kalshi code must never inherit Polymarket-specific settlement
or orderbook assumptions.
"""
