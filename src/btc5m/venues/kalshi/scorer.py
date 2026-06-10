"""Fast, preloaded scorer abstraction for the Kalshi hot path.

The model (and, later, a calibrator) is loaded ONCE at construction — never per
tick. :meth:`score` reads a flat feature snapshot (the ``build_feature_row`` dict)
and returns a probability + diagnostics. With no trained/calibrated artifact on
disk it falls back to the neutral/uncalibrated :class:`BaselineModel`, reports
``calibration_status="uncalibrated"``, and therefore can NEVER unlock a
PAPER_CANDIDATE (the EV layer blocks uncalibrated models). No fake artifacts are
created; the neutral model is never presented as profitable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ...models.baseline import BaselineInputs, BaselineModel
from ...schemas import Comparison
from .features import FEATURE_SET_VERSION


@dataclass
class ScoreResult:
    p_yes: Optional[float]
    p_yes_lower: Optional[float]
    p_yes_upper: Optional[float]
    calibrated: bool
    calibration_status: str            # "calibrated" | "uncalibrated"
    model_version: str
    feature_schema_version: int
    reason: Optional[str] = None       # e.g. INSUFFICIENT_INPUTS


class KalshiScorer:
    """Preloaded probability scorer (neutral baseline until a model is trained)."""

    def __init__(self, config: Any = None, *, model: Any = None, calibrator: Any = None) -> None:
        self.config = config
        # Loaded ONCE — the hot path must never construct/load these per score.
        self.model = model if model is not None else BaselineModel(config)
        self.calibrator = calibrator if calibrator is not None else self._load_calibrator(config)
        self.model_version = getattr(self.model, "name", "baseline-normal")
        self.feature_schema_version = FEATURE_SET_VERSION

    @staticmethod
    def _load_calibrator(config: Any) -> Optional[Any]:
        """Load a persisted calibrator artifact if one exists (once).

        None today: no calibrated artifact is shipped, and we never fabricate one.
        When a real calibrator is fit + saved, load it here so the hot path can
        unlock PAPER_CANDIDATE — until then the scorer stays honestly uncalibrated.
        """
        return None

    @property
    def calibrated(self) -> bool:
        return self.calibrator is not None

    @property
    def calibration_status(self) -> str:
        return "calibrated" if self.calibrated else "uncalibrated"

    def score(self, snapshot: dict) -> ScoreResult:
        """Score a point-in-time feature snapshot. O(1); no I/O, no model load."""
        inp = BaselineInputs(
            reference_price=snapshot.get("reference_price"),
            line=snapshot.get("reference_start_price"),
            seconds_to_expiry=snapshot.get("seconds_to_close"),
            sigma_per_sqrt_s=snapshot.get("spot_sigma_per_sqrt_s"),
            comparison=Comparison.GTE,
        )
        out = self.model.predict_proba(inp)
        p = out.p_yes
        if self.calibrator is not None and p is not None:
            try:
                p = float(self.calibrator.transform([p])[0])
            except Exception:  # noqa: BLE001 - never let a calibrator crash the hot path
                p = out.p_yes
        insufficient = snapshot.get("reference_price") is None or snapshot.get("reference_start_price") is None
        return ScoreResult(
            p_yes=p,
            p_yes_lower=out.p_yes_lower,
            p_yes_upper=out.p_yes_upper,
            calibrated=self.calibrated,
            calibration_status=self.calibration_status,
            model_version=self.model_version,
            feature_schema_version=self.feature_schema_version,
            reason=("INSUFFICIENT_INPUTS" if insufficient else None),
        )
