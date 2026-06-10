"""Model ensemble (scaffold).

Combines linear, gradient-boosted, and quantile estimates into a single
calibrated probability. The ensemble output must itself be calibrated.
"""

from __future__ import annotations

from typing import Any


class Ensemble:
    name = "ensemble"

    def __init__(self, members: list[Any] | None = None):
        self.members = members or []

    def predict_proba(self, X: Any) -> Any:
        raise NotImplementedError("Ensemble.predict_proba is a scaffold.")
