"""Probability calibration (mandatory) — isotonic, dependency-free.

Calibration maps raw model scores to calibrated probabilities. Accuracy alone is
never sufficient: a model must be calibrated and its reliability reported.

:class:`IsotonicCalibrator` implements isotonic regression via the
Pool-Adjacent-Violators Algorithm (PAVA) in the standard library, so no sklearn
dependency is required. It is fit on a held-out, leakage-safe set and produces a
monotonic non-decreasing mapping from raw score to calibrated probability.

Reports (reliability curve, Brier, log loss, ECE) live in
:mod:`btc5m.backtest.metrics`; :func:`reliability_report` bundles them.
"""

from __future__ import annotations

from typing import Optional, Sequence

from ..timeutils import now_ms


def _pava(x: Sequence[float], y: Sequence[float]) -> tuple[list[float], list[float]]:
    """Pool-Adjacent-Violators: returns (sorted_x_thresholds, fitted_values)."""
    order = sorted(range(len(x)), key=lambda i: x[i])
    xs = [x[i] for i in order]
    ys = [y[i] for i in order]
    # Each block: [sum_y, count, value, x_right]
    blocks: list[list[float]] = []
    for xi, yi in zip(xs, ys):
        blocks.append([yi, 1.0, yi, xi])
        while len(blocks) >= 2 and blocks[-2][2] > blocks[-1][2]:
            s2, c2, _, xr = blocks.pop()
            s1, c1, _, _ = blocks.pop()
            s, c = s1 + s2, c1 + c2
            blocks.append([s, c, s / c, xr])
    thresholds = [b[3] for b in blocks]
    values = [b[2] for b in blocks]
    return thresholds, values


class IsotonicCalibrator:
    """Monotonic non-decreasing score->probability calibrator (PAVA)."""

    method = "isotonic"

    def __init__(self) -> None:
        self._x: list[float] = []
        self._y: list[float] = []
        self.fitted_ts_ms: Optional[int] = None

    def fit(self, scores: Sequence[float], outcomes: Sequence[int]) -> "IsotonicCalibrator":
        if len(scores) != len(outcomes):
            raise ValueError("scores and outcomes must be the same length")
        if not scores:
            raise ValueError("cannot fit on empty data")
        self._x, self._y = _pava(scores, [float(o) for o in outcomes])
        self.fitted_ts_ms = now_ms()
        return self

    def transform_one(self, score: float) -> float:
        if not self._x:
            raise RuntimeError("calibrator not fitted")
        # Step interpolation on the non-decreasing fitted curve.
        if score <= self._x[0]:
            return _clip(self._y[0])
        if score >= self._x[-1]:
            return _clip(self._y[-1])
        lo, hi = 0, len(self._x) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self._x[mid] < score:
                lo = mid + 1
            else:
                hi = mid
        # Linear interpolate between neighboring thresholds for smoothness.
        i = max(1, lo)
        x0, x1 = self._x[i - 1], self._x[i]
        y0, y1 = self._y[i - 1], self._y[i]
        if x1 == x0:
            return _clip(y1)
        t = (score - x0) / (x1 - x0)
        return _clip(y0 + t * (y1 - y0))

    def transform(self, scores: Sequence[float]) -> list[float]:
        return [self.transform_one(s) for s in scores]


def _clip(p: float, eps: float = 1e-6) -> float:
    return min(1 - eps, max(eps, p))


# Backwards-compatible alias.
Calibrator = IsotonicCalibrator


def reliability_report(
    probs: Sequence[float], outcomes: Sequence[int], *, n_bins: int = 10
) -> dict:
    """Bundle calibration diagnostics: Brier, log loss, ECE, reliability table."""
    from ..backtest.metrics import (
        brier_score,
        expected_calibration_error,
        log_loss,
        reliability_table,
    )

    return {
        "n": len(probs),
        "brier": brier_score(probs, outcomes),
        "log_loss": log_loss(probs, outcomes),
        "ece": expected_calibration_error(probs, outcomes, n_bins=n_bins),
        "reliability": reliability_table(probs, outcomes, n_bins=n_bins),
    }
