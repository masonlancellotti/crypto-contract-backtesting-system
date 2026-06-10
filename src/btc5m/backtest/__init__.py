"""Backtesting: event replay, execution simulation, validation, metrics, reports.

The execution simulator never assumes midpoint fills — it walks the book and
charges fees. Validation uses purge/embargo; metrics emphasize calibration and
net-of-cost PnL, not raw accuracy.
"""
