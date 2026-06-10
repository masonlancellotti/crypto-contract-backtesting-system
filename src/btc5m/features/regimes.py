"""Volatility / liquidity regime features (scaffold).

Classifies the current short-term regime (e.g. low/normal/high realized vol,
thin/normal liquidity) used to condition the settlement-probability model.
"""

from __future__ import annotations

from typing import Any


def classify_regime(window: Any) -> dict:
    """Return regime labels/scores for the current window. Scaffold."""
    raise NotImplementedError("classify_regime is a scaffold.")
