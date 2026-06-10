"""Linear microstructure model (scaffold).

A transparent logistic baseline over microstructure + duration features. Useful
as an interpretable reference and for ablations against the gradient-boosted
model. Requires fitting on purged/embargoed data before use.
"""

from __future__ import annotations

from typing import Any


class LinearMicrostructureModel:
    name = "linear-microstructure"

    def fit(self, X: Any, y: Any) -> "LinearMicrostructureModel":
        raise NotImplementedError("LinearMicrostructureModel.fit is a scaffold.")

    def predict_proba(self, X: Any) -> Any:
        raise NotImplementedError("LinearMicrostructureModel.predict_proba is a scaffold.")
