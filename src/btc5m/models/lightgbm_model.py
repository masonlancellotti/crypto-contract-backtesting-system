"""Gradient-boosted settlement-probability model (scaffold).

LightGBM is imported lazily so this module imports without the dependency. Must
be trained with purge/embargo and evaluated on calibration (not just accuracy)
plus ablations before being considered for paper or live use.
"""

from __future__ import annotations

from typing import Any


class LightGBMModel:
    name = "lightgbm"

    def __init__(self, params: dict | None = None):
        self.params = params or {}
        self._booster = None

    def fit(self, X: Any, y: Any) -> "LightGBMModel":
        # import lightgbm  # lazy, optional
        raise NotImplementedError("LightGBMModel.fit is a scaffold.")

    def predict_proba(self, X: Any) -> Any:
        raise NotImplementedError("LightGBMModel.predict_proba is a scaffold.")
