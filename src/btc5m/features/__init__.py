"""Feature engineering for 5-minute BTC binary settlement probability.

Features cover the Polymarket contract microstructure, the underlying BTC
microstructure (order flow, queue imbalance, microprice), time-to-expiry
duration effects, and volatility regimes. All scaffolds return typed, explicit
values; none assume midpoint pricing or ignore quote age.
"""
