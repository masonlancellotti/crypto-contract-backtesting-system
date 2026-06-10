"""Kalshi binary-price units — single source of truth.

The repo standardizes on **DECIMAL probability/dollars 0.0–1.0** internally (matching
the normalized order book); human-facing thresholds and summaries use cents. These
helpers make conversions explicit so lifecycle / lock / EV math never mixes units.

A Kalshi YES contract pays $1 if YES resolves; its price is a probability in
[0, 1] (equivalently 0–100 cents). Fees are computed on the decimal price.
"""

from __future__ import annotations

from typing import Optional

PRICE_UNIT = "decimal"  # canonical internal unit


def price_unit_name() -> str:
    """Name of the canonical internal price unit ('decimal')."""
    return PRICE_UNIT


def to_decimal_price(p, *, assume: str = "decimal") -> Optional[float]:
    """Coerce a price to decimal 0.0–1.0. ``assume='cents'`` divides by 100.

    Returns None for non-numeric input. Does not clamp — use
    :func:`validate_binary_price` to range-check.
    """
    if p is None:
        return None
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if assume == "cents":
        v /= 100.0
    elif assume != "decimal":
        raise ValueError(f"assume must be 'decimal' or 'cents', got {assume!r}")
    return v


def to_cents_price(p, *, assume: str = "decimal") -> Optional[float]:
    """Coerce a price to cents 0–100. ``assume='cents'`` passes through."""
    if p is None:
        return None
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if assume == "decimal":
        v *= 100.0
    elif assume != "cents":
        raise ValueError(f"assume must be 'decimal' or 'cents', got {assume!r}")
    return v


def validate_binary_price(p, *, unit: str = "decimal") -> bool:
    """True iff ``p`` is a numeric binary price within bounds for ``unit``.

    decimal: 0.0 <= p <= 1.0 · cents: 0 <= p <= 100. Booleans are rejected.
    """
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        return False
    hi = 1.0 if unit == "decimal" else 100.0 if unit == "cents" else None
    if hi is None:
        raise ValueError(f"unit must be 'decimal' or 'cents', got {unit!r}")
    return 0.0 <= float(p) <= hi


def format_price_cents(p, *, assume: str = "decimal") -> str:
    """Human cents string, e.g. 0.68 -> '68c', 0.681 -> '68.1c', None -> 'n/a'."""
    c = to_cents_price(p, assume=assume)
    if c is None:
        return "n/a"
    return f"{round(c)}c" if abs(c - round(c)) < 1e-6 else f"{c:.1f}c"
