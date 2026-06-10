"""Quantile / distributional model for the underlying path (scaffold).

Models the distribution of BTC return over the remaining window so settlement
probability can be derived as P(path ends above line). Provides uncertainty for
the WATCH/MANUAL_REVIEW gating.
"""

from __future__ import annotations

from typing import Any


class QuantileModel:
    name = "quantile"

    def fit(self, X: Any, y: Any) -> "QuantileModel":
        raise NotImplementedError("QuantileModel.fit is a scaffold.")

    def predict_quantiles(self, X: Any) -> Any:
        raise NotImplementedError("QuantileModel.predict_quantiles is a scaffold.")
