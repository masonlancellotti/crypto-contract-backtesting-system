"""Evaluation metrics.

Brier score is implemented (stdlib) because calibration is central. Net-of-cost
PnL, hit rate, and edge-bucket metrics are scaffolds pending real fills. Models
are never judged by accuracy alone.
"""

from __future__ import annotations

import math
from typing import Sequence


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error between predicted probabilities and {0,1} outcomes."""
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must be the same length")
    if not probs:
        raise ValueError("empty inputs")
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / len(probs)


def hit_rate(probs: Sequence[float], outcomes: Sequence[int], *, threshold: float = 0.5) -> float:
    """Fraction correct when thresholding probabilities (diagnostic only)."""
    if not probs:
        raise ValueError("empty inputs")
    correct = sum(1 for p, y in zip(probs, outcomes) if int(p >= threshold) == y)
    return correct / len(probs)


def log_loss(probs: Sequence[float], outcomes: Sequence[int], *, eps: float = 1e-15) -> float:
    """Binary cross-entropy. Clipped to avoid log(0)."""
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must be the same length")
    if not probs:
        raise ValueError("empty inputs")
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = min(1 - eps, max(eps, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def reliability_table(
    probs: Sequence[float], outcomes: Sequence[int], *, n_bins: int = 10
) -> list[dict]:
    """Reliability buckets: predicted-prob bin vs realized frequency.

    Returns a list of dicts (one per non-empty bin) with bin range, count, mean
    predicted probability, and realized positive frequency.
    """
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must be the same length")
    bins: list[dict] = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [
            i for i, p in enumerate(probs)
            if (p >= lo and (p < hi or (b == n_bins - 1 and p <= hi)))
        ]
        if not idx:
            continue
        mean_pred = sum(probs[i] for i in idx) / len(idx)
        frac_pos = sum(outcomes[i] for i in idx) / len(idx)
        bins.append({
            "bin_lo": lo, "bin_hi": hi, "count": len(idx),
            "mean_pred": mean_pred, "frac_pos": frac_pos,
            "gap": frac_pos - mean_pred,
        })
    return bins


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[int], *, n_bins: int = 10
) -> float:
    """ECE: count-weighted mean |frac_pos - mean_pred| over reliability bins."""
    table = reliability_table(probs, outcomes, n_bins=n_bins)
    n = len(probs)
    if n == 0:
        raise ValueError("empty inputs")
    return sum(row["count"] * abs(row["gap"]) for row in table) / n
