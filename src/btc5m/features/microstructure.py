"""Underlying BTC microstructure features (scaffold).

Aggregates spot/futures book + trade flow into features predictive of short-term
drift and realized volatility over the remaining seconds of the 5-minute window.
"""

from __future__ import annotations

from typing import Any


def microstructure_features(window: Any) -> dict:
    """Compute microstructure features from a market-data window. Scaffold."""
    raise NotImplementedError(
        "microstructure_features is a scaffold. Implement spot/futures aggregation."
    )
